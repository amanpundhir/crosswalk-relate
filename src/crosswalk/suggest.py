"""Q5: mapping suggestions for a control (``crosswalk suggest``).

``suggest(conn, control_id, framework, k, method)`` returns requirement candidates of one framework:

=================  =====================================================================================
``fulltext``       BM25 keyword search on requirement title + text (queries/q5_suggest_fulltext.cypher)
``vector``         cosine search on the 384-d embeddings (q5_suggest_vector.cypher)
``hybrid``         weighted reciprocal-rank fusion of the two, 0.7 / 0.3, constant 60 (q5_suggest_hybrid)
``hybrid+graph``   hybrid candidates re-ranked with graph context (q5_graph_signals.cypher): a family
                   that already holds approved mappings of the control's policy siblings, crosswalk
                   neighbours of requirements the control already satisfies, and a penalty for a
                   mapping a human already rejected for this control
=================  =====================================================================================

Each suggestion is a dict ``{id, title, score, method, signals, paths, path_id}``.  ``signals`` lists the
per-signal contributions (``vector``/``fulltext`` with raw score, rank and contribution; ``graph`` with the
boosts that fired).  ``paths`` holds one ``{signal, id, nodes, rels}`` per graph signal used (ids from
:mod:`crosswalk.paths`, replayable with ``queries.check_path``); ``path_id`` is the first of them or None.

``ignore_own=True`` is leave-one-out for evaluation: the control's own approved SATISFIES edges and its own
proposals and decisions are not used as graph signals.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

import relate

from crosswalk import embed as _embed
from crosswalk.build import QUERIES_DIR
from crosswalk.coverage import normalise_framework
from crosswalk.paths import make_path

log = logging.getLogger("crosswalk.suggest")

METHODS = ("fulltext", "vector", "hybrid", "hybrid+graph")

W_VEC = 0.7
W_FT = 0.3
RRF_C = 60
POOL = 50            # candidates taken from each method before fusion
FT_POOL = 2000       # raw full-text hits pulled before the framework filter (> number of requirements)
GRAPH_POOL = 30      # hybrid candidates that the graph re-rank looks at
BOOST_FAMILY = 0.15  # added to a hybrid score that was min-max normalised over the pool (0..1)
BOOST_CROSSWALK = 0.25
PENALTY_REJECTED = 1.0
MAX_PATHS_PER_SIGNAL = 3
MAX_QUERY_TERMS = 60


class SuggestError(RuntimeError):
    """A suggestion could not be made (unknown control or framework, missing index or embedding)."""


# --------------------------------------------------------------------------
# Query text
# --------------------------------------------------------------------------

# Relate's full-text query language treats AND / OR / NOT, quotes, parentheses, field:, wildcards (*, ?),
# fuzzy (~) and boost (^) as syntax.  A control sentence is only ever a bag of words, so everything except
# letters and digits is dropped, the operator words and stop words go, and the rest is joined by spaces
# (Relate's default is OR).  The result is always safe to pass as $q.
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""
a an and are as at be by for from has have in is it its of on or not that the their them these this those to
was were will with within which who may must shall should can any all each per into than then there such
other including include includes also upon via
""".split())


def sanitise_query(text: str | None, max_terms: int = MAX_QUERY_TERMS) -> str:
    """Bag-of-words full-text query from free text; never contains Relate query syntax."""
    seen: dict[str, None] = {}
    for w in _WORD.findall((text or "").lower()):
        if len(w) < 2 or w in _STOP:
            continue
        seen.setdefault(w, None)
        if len(seen) >= max_terms:
            break
    return " ".join(seen)


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _text(name: str) -> str:
    return (QUERIES_DIR / f"{name}.cypher").read_text(encoding="utf-8")


def _run(conn: relate.Connection, name: str, params: dict[str, Any]) -> list[dict]:
    return [dict(r) for r in conn.execute(_text(name), params).fetchall()]


def _control(conn: relate.Connection, control_id: str) -> dict:
    rows = _run(conn, "q5_control", {"control": control_id})
    if not rows:
        raise SuggestError(f"no control {control_id!r}")
    c = rows[0]
    if not c["embedding"]:  # a control added after the build: embed it now if the model is around
        try:
            got = _embed.embeddings_for([(c["id"], _embed.control_text(c))], write_cache=False)
            c["embedding"] = got.get(c["id"])
        except Exception:  # noqa: BLE001
            c["embedding"] = None
    c["query"] = sanitise_query(_embed.control_text(c))
    return c


def _has_index(conn: relate.Connection, name: str) -> bool:
    return any(r["name"] == name for r in conn.execute("SHOW INDEXES").fetchall())


def _params(framework: str, k: int, **extra: Any) -> dict[str, Any]:
    return {"framework": framework, "k": int(k), "pool": POOL, "ft_pool": FT_POOL,
            "w_vec": W_VEC, "w_ft": W_FT, "rrf_c": RRF_C, **extra}


# --------------------------------------------------------------------------
# the three retrieval methods
# --------------------------------------------------------------------------


def _fulltext(conn: relate.Connection, c: dict, framework: str, k: int) -> list[dict]:
    if not c["query"]:
        return []
    rows = _run(conn, "q5_suggest_fulltext", _params(framework, k, q=c["query"]))
    return [{"id": r["id"], "title": r["title"], "score": r["score"], "method": "fulltext",
             "signals": {"fulltext": {"score": r["score"], "rank": i, "contribution": r["score"]}},
             "paths": [], "path_id": None} for i, r in enumerate(rows, 1)]


def _vector(conn: relate.Connection, c: dict, framework: str, k: int) -> list[dict]:
    if not c["embedding"]:
        raise SuggestError(f"{c['id']} has no embedding and the embedding model is not available")
    rows = _run(conn, "q5_suggest_vector", _params(framework, k, v=c["embedding"]))
    return [{"id": r["id"], "title": r["title"], "score": r["score"], "method": "vector",
             "signals": {"vector": {"score": r["score"], "rank": i, "contribution": r["score"]}},
             "paths": [], "path_id": None} for i, r in enumerate(rows, 1)]


def _hybrid(conn: relate.Connection, c: dict, framework: str, k: int) -> list[dict]:
    if not c["embedding"]:
        log.warning("%s has no embedding: hybrid search falls back to full text only", c["id"])
        return [{**x, "method": "hybrid"} for x in _fulltext(conn, c, framework, k)]
    rows = _run(conn, "q5_suggest_hybrid", _params(framework, k, v=c["embedding"], q=c["query"] or "zzzznomatch"))
    out = []
    for r in rows:
        sig: dict[str, Any] = {}
        if r["vector_rank"] is not None:
            sig["vector"] = {"score": r["vector_score"], "rank": r["vector_rank"], "contribution": r["vector_part"]}
        if r["fulltext_rank"] is not None:
            sig["fulltext"] = {"score": r["fulltext_score"], "rank": r["fulltext_rank"],
                               "contribution": r["fulltext_part"]}
        out.append({"id": r["id"], "title": r["title"], "score": r["score"], "method": "hybrid",
                    "signals": sig, "paths": [], "path_id": None})
    return out


# --------------------------------------------------------------------------
# graph re-rank
# --------------------------------------------------------------------------


def graph_signals(conn: relate.Connection, control_id: str, framework: str, ignore_own: bool = False) -> dict:
    """``{"family": {family: [via...]}, "crosswalk": {cand: [via...]}, "rejected": {cand: [via...]}}``."""
    rows = _run(conn, "q5_graph_signals", {"control": control_id, "framework": framework,
                                           "ignore_own": bool(ignore_own)})
    out: dict[str, dict[str, list[dict]]] = {"family": {}, "crosswalk": {}, "rejected": {}}
    for r in rows:
        d = r["data"]
        if r["kind"] == "family":
            out["family"][d["family"]] = sorted(d["via"], key=lambda x: (x["sibling"], x["requirement"]))
        else:
            out[r["kind"]].setdefault(d["candidate"], []).append(d)
    return out


def _rerank(conn: relate.Connection, c: dict, framework: str, k: int, ignore_own: bool) -> list[dict]:
    cands = _hybrid(conn, c, framework, max(GRAPH_POOL, k))
    if not cands:
        return []
    sig = graph_signals(conn, c["id"], framework, ignore_own)
    fam_of = {r["id"]: r["family"] for r in _run(conn, "q5_candidate_family", {"ids": [x["id"] for x in cands]})}
    scores = [x["score"] for x in cands]
    lo, hi = min(scores), max(scores)
    out = []
    for x in cands:
        base = (x["score"] - lo) / (hi - lo) if hi > lo else 1.0
        graph: dict[str, Any] = {}
        paths: list[dict] = []
        total = base
        fam = fam_of.get(x["id"])
        if fam in sig["family"]:
            via = sig["family"][fam]
            graph["family"] = {"contribution": BOOST_FAMILY, "family": fam,
                               "siblings": sorted({v["sibling"] for v in via})}
            total += BOOST_FAMILY
            for v in via[:MAX_PATHS_PER_SIGNAL]:
                paths.append({"signal": "family",
                              **make_path(v["nodes"] + [f"Requirement:{x['id']}"], v["rels"] + ["PART_OF<-"])})
        for v in sig["crosswalk"].get(x["id"], [])[:MAX_PATHS_PER_SIGNAL]:
            graph.setdefault("crosswalk", {"contribution": BOOST_CROSSWALK, "via": []})["via"].append(v["via"])
            paths.append({"signal": "crosswalk", **make_path(v["nodes"], v["rels"])})
        if "crosswalk" in graph:
            total += BOOST_CROSSWALK
        for v in sig["rejected"].get(x["id"], [])[:1]:
            graph["rejected"] = {"contribution": -PENALTY_REJECTED, "proposal": v["proposal"],
                                 "decision": v["decision"], "reason": v["reason"], "by": v["by"]}
            total -= PENALTY_REJECTED
            paths.append({"signal": "rejected", **make_path(v["nodes"], v["rels"])})
        signals = dict(x["signals"])
        signals["hybrid"] = {"score": x["score"], "normalised": round(base, 6)}
        if graph:
            signals["graph"] = graph
        out.append({"id": x["id"], "title": x["title"], "score": round(total, 6), "method": "hybrid+graph",
                    "signals": signals, "paths": paths, "path_id": paths[0]["id"] if paths else None,
                    "_hybrid": x["score"]})
    out.sort(key=lambda r: (-r["score"], -r["_hybrid"], r["id"]))
    for r in out:
        del r["_hybrid"]
    return out[:k]


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------


def suggest(conn: relate.Connection, control_id: str, framework: str, k: int = 10,
            method: str = "hybrid", ignore_own: bool = False) -> list[dict]:
    """Top-``k`` requirements of ``framework`` that ``control_id`` might satisfy, best first."""
    if method not in METHODS:
        raise SuggestError(f"unknown method {method!r}; choose one of {', '.join(METHODS)}")
    fw = normalise_framework(framework)
    if not conn.execute("MATCH (r:Requirement {framework: $f}) RETURN count(r) AS n", {"f": fw}).fetchall()[0]["n"]:
        raise SuggestError(f"no requirements for framework {framework!r}")
    if method != "fulltext" and not _has_index(conn, "requirement_embedding"):
        raise SuggestError("the store has no vector index (built without embeddings); use method 'fulltext' "
                           "or rebuild with `crosswalk build`")
    c = _control(conn, control_id)
    if method == "fulltext":
        return _fulltext(conn, c, fw, k)
    if method == "vector":
        return _vector(conn, c, fw, k)
    if method == "hybrid":
        return _hybrid(conn, c, fw, k)
    return _rerank(conn, c, fw, k, ignore_own)
