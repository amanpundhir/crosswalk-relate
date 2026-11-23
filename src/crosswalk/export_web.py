"""Export the Crosswalk store for the static browser explorer (``web/``).

    python -m crosswalk.export_web            # data/crosswalk -> web/data/*, web/queries/*

The browser build of Relate (WASM) cannot open a store, so the explorer rebuilds the graph in memory
from ``web/data/graph.cypher``: one statement per line, no embeddings, no long text, deterministic
(sorted, no clock).  Alongside it:

* ``web/data/meta.json``       as_of, node/relationship counts, frameworks, audits, graph hash
* ``web/data/scorecard.json``  a copy of ``eval/scorecard.json`` (skipped when it does not exist)
* ``web/data/live-catch.json`` the recorded agent answer of the live-catch demo (skipped when missing);
                               the browser re-checks its cited paths live with check_path.cypher
* ``web/queries/*.cypher``     the SAME query text the CLI runs (copied byte for byte)

The store is only read, through a read-only connection.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import relate

from crosswalk.build import DEFAULT_STORE, QUERIES_DIR, REPO_ROOT, resolve_store
from crosswalk.sources.nist import natural_key

WEB_DIR = REPO_ROOT / "web"
SCORECARD = REPO_ROOT / "eval" / "scorecard.json"
LIVE_CATCH = REPO_ROOT / "eval" / "agent-runs" / "live-catch-recorded.json"

# Node labels in load order (also the order the rebuilt graph's statements appear in).
LABELS = ["Framework", "Family", "Requirement", "Person", "System", "Policy", "Control", "Evidence",
          "Audit", "Agent", "Proposal", "Decision", "TrackerRow", "Meta"]
# Properties the browser does not need (keeps graph.cypher small).
DROP_ALL = {"embedding", "text_sha", "context", "built_at_source_shas"}
DROP_BY_LABEL = {"Requirement": {"text"}}
# Queries the explorer runs: text identical to queries/*.cypher (the q5 suggest queries need the
# vector and full-text indexes, which the browser build does not have, so they are not copied).
BROWSER_QUERIES = ["q1_coverage", "q1_paths", "q2_adopt", "q3_blast", "q4_reuse", "q6_owner_risk",
                   "explain", "check_path", "proposed_paths"]
NODE_BATCH = 100
REL_BATCH = 400


# --------------------------------------------------------------------------
# Cypher literals
# --------------------------------------------------------------------------


def lit(v: Any) -> str:
    """A Cypher literal for a property value (dates become ``date('YYYY-MM-DD')``)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, _dt.datetime):
        raise TypeError("datetimes are not used in the graph")
    if isinstance(v, _dt.date):
        return f"date('{v.isoformat()}')"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON escapes are valid Cypher escapes
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(lit(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} as a Cypher literal")


def _props(label: str, props: dict[str, Any]) -> dict[str, Any]:
    drop = DROP_ALL | DROP_BY_LABEL.get(label, set())
    return {k: props[k] for k in sorted(props) if k not in drop and props[k] is not None}


def _map(props: dict[str, Any]) -> str:
    return "{" + ", ".join(f"{k}: {lit(v)}" for k, v in props.items()) + "}"


def _sort_key(item_id: Any) -> Any:
    return natural_key(str(item_id))


# --------------------------------------------------------------------------
# Graph -> statements
# --------------------------------------------------------------------------


def _read_graph(conn: relate.Connection) -> tuple[dict[str, list[dict]], list[dict]]:
    nodes: dict[str, list[dict]] = {label: [] for label in LABELS}
    for r in conn.execute("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props").fetchall():
        label = r["labels"][0]
        if label not in nodes:
            raise ValueError(f"unexpected label {label!r}: add it to export_web.LABELS")
        nodes[label].append(_props(label, dict(r["props"])))
    for label in nodes:
        nodes[label].sort(key=lambda p: _sort_key(p["id"]))
    rels = [dict(r) for r in conn.execute(
        "MATCH (a)-[r]->(b) RETURN type(r) AS type, labels(a)[0] AS al, a.id AS aid, "
        "labels(b)[0] AS bl, b.id AS bid, properties(r) AS props").fetchall()]
    rels.sort(key=lambda r: (r["type"], r["al"], r["bl"], _sort_key(r["aid"]), _sort_key(r["bid"])))
    return nodes, rels


def build_statements(nodes: dict[str, list[dict]], rels: list[dict]) -> list[str]:
    """Cypher statements (one per list entry, no trailing semicolon) that rebuild the graph."""
    out: list[str] = []
    for label in ("Framework", "Family", "Requirement", "Person", "System", "Policy", "Control", "Evidence",
                  "Audit", "Agent", "Proposal", "Decision", "TrackerRow", "Meta"):
        rows = nodes[label]
        for i in range(0, len(rows), NODE_BATCH):
            chunk = rows[i:i + NODE_BATCH]
            out.append("CREATE " + ", ".join(f"(:{label} {_map(p)})" for p in chunk))
    # relationships, grouped by (type, from label, to label); property keys are uniform per group
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for r in rels:
        groups.setdefault((r["type"], r["al"], r["bl"]), []).append(r)
    for (typ, al, bl), items in groups.items():
        keys = sorted({k for r in items for k in r["props"]})
        dates = {k for r in items for k, v in r["props"].items() if isinstance(v, _dt.date)}
        prop_txt = ""
        if keys:
            prop_txt = " {" + ", ".join(f"{k}: " + (f"date(r.{k})" if k in dates else f"r.{k}") for k in keys) + "}"
        for i in range(0, len(items), REL_BATCH):
            chunk = items[i:i + REL_BATCH]
            rows = []
            for r in chunk:
                row = {"a": r["aid"], "b": r["bid"]}
                row.update({k: (v.isoformat() if isinstance(v, _dt.date) else v)
                            for k, v in sorted(r["props"].items())})
                rows.append("{" + ", ".join(f"{k}: {lit(v)}" for k, v in row.items()) + "}")
            out.append(f"UNWIND [{', '.join(rows)}] AS r MATCH (a:{al} {{id: r.a}}) MATCH (b:{bl} {{id: r.b}}) "
                       f"CREATE (a)-[:{typ}{prop_txt}]->(b)")
    return out


def render_script(statements: list[str], counts_line: str) -> str:
    head = ["// Crosswalk graph for the browser explorer (generated by `python -m crosswalk.export_web`).",
            "// One statement per line, each ending in ';'. Lines starting with // are comments.",
            f"// {counts_line}"]
    return "\n".join(head + [s + ";" for s in statements]) + "\n"


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------


def build_meta(nodes: dict[str, list[dict]], rels: list[dict], n_statements: int, script_sha: str,
               has_scorecard: bool, has_live_catch: bool) -> dict[str, Any]:
    meta_node = nodes["Meta"][0]
    rel_counts: dict[str, int] = {}
    for r in rels:
        rel_counts[r["type"]] = rel_counts.get(r["type"], 0) + 1
    fw_req = {f["id"]: 0 for f in nodes["Framework"]}
    for r in nodes["Requirement"]:
        fw_req[r["framework"]] += 1
    audits = []
    scopes = {(r["aid"]): r["bid"] for r in rels if r["type"] == "SCOPES"}
    for a in sorted(nodes["Audit"], key=lambda a: (a["date"], a["id"])):
        audits.append({"id": a["id"], "name": a["name"], "date": a["date"].isoformat(),
                       "framework": scopes.get(a["id"]), "scope_baseline": a.get("scope_baseline")})
    return {
        "company": meta_node.get("company"),
        "as_of": meta_node["as_of"].isoformat(),
        "nodes": {label: len(rows) for label, rows in sorted(nodes.items())},
        "total_nodes": sum(len(r) for r in nodes.values()),
        "relationships": dict(sorted(rel_counts.items())),
        "total_relationships": len(rels),
        "frameworks": [{"id": f["id"], "name": f["name"], "version": f["version"], "requirements": fw_req[f["id"]]}
                       for f in nodes["Framework"]],
        "audits": audits,
        "statements": n_statements,
        "graph_cypher_sha256": script_sha,
        "queries": BROWSER_QUERIES,
        "has_scorecard": has_scorecard,
        "has_live_catch": has_live_catch,
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def export_web(store_dir: str | Path = DEFAULT_STORE, out_dir: str | Path = WEB_DIR) -> dict[str, Any]:
    """Write ``graph.cypher``, ``meta.json``, the queries and (if present) the scorecard. Returns the meta."""
    out = Path(out_dir)
    conn = relate.connect(str(resolve_store(store_dir)), read_only=True)
    try:
        nodes, rels = _read_graph(conn)
    finally:
        conn.close()
    statements = build_statements(nodes, rels)
    total_n = sum(len(r) for r in nodes.values())
    script = render_script(statements, f"{total_n} nodes, {len(rels)} relationships, no embeddings")
    script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()

    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "graph.cypher").write_text(script, encoding="utf-8", newline="\n")

    scorecard_dst = data_dir / "scorecard.json"
    has_scorecard = SCORECARD.exists()
    if has_scorecard:
        shutil.copyfile(SCORECARD, scorecard_dst)
    elif scorecard_dst.exists():
        scorecard_dst.unlink()  # never leave a stale scorecard behind

    live_dst = data_dir / "live-catch.json"
    has_live = LIVE_CATCH.exists()
    if has_live:
        shutil.copyfile(LIVE_CATCH, live_dst)
    elif live_dst.exists():
        live_dst.unlink()

    meta = build_meta(nodes, rels, len(statements), script_sha, has_scorecard, has_live)
    (data_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                        encoding="utf-8", newline="\n")

    q_dir = out / "queries"
    q_dir.mkdir(parents=True, exist_ok=True)
    for name in BROWSER_QUERIES:
        shutil.copyfile(QUERIES_DIR / f"{name}.cypher", q_dir / f"{name}.cypher")
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m crosswalk.export_web", description=__doc__.split("\n")[0])
    ap.add_argument("--store", default=str(DEFAULT_STORE), help="Relate directory store (read only)")
    ap.add_argument("--out", default=str(WEB_DIR), help="web directory to write into")
    args = ap.parse_args(argv)
    meta = export_web(args.store, args.out)
    size = (Path(args.out) / "data" / "graph.cypher").stat().st_size
    print(f"web/data/graph.cypher  {size:,} bytes  {meta['total_nodes']} nodes, "
          f"{meta['total_relationships']} relationships, {meta['statements']} statements")
    print(f"as_of {meta['as_of']}  scorecard: {'copied' if meta['has_scorecard'] else 'not found, skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
