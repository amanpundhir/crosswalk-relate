"""The claim checker: how "answers with receipts" are verified.

An *answer* is plain JSON::

    {"question": "...", "agent": "audit-prep",
     "claims": [{"text": "03.05.03 is covered by CTRL-REAP-6", "path_ids": ["P-94fd053fec24"], "kind": "coverage"}]}

Every claim must cite path ids (see :mod:`crosswalk.paths`).  :func:`check_claims` resolves each id back
to its nodes and relationships, re-runs it with :func:`crosswalk.queries.check_path` at ``Meta.as_of`` and
gives each path a verdict with a precise human reason, then each claim a verdict:

======================  ==========  ============================================================
path ``code``           ``status``  meaning
======================  ==========  ============================================================
``valid``               ok          the path exists and every hop is valid at as_of
``proposed_mapping``    warn        a mapping on the path is only proposed (pending), not approved
``expired_evidence``    fail        evidence on the path expired ("EV-044 expired 2026-12-01")
``rejected_mapping``    fail        a human rejected the proposal behind the path
``not_adopted``         fail        a control on the path is not adopted
``no_evidence``         fail        a ``coverage`` claim cites a requirement-control path with no evidence
``broken_structure``    fail        the path does not exist in the graph (a hop is missing)
``unknown_path``        fail        the id was never issued by a tool and cannot be rebuilt
======================  ==========  ============================================================

Claim verdict: ``verified`` (every cited path ok), ``failed`` (a claim with no path id at all, "no
receipt", or no cited path is ok and at least one failed) or ``partial`` (otherwise: a mix of ok and
not-ok paths, or only pending proposals).  Symbols: verified ``✔``, partial ``⚠``, failed ``✖``.

Path registry (id -> nodes, rels)
---------------------------------
A path id is a one-way hash, so something has to remember what it stands for.  :class:`PathRegistry`
is an **in-process dict**: every tool response is passed through :meth:`PathRegistry.register_result`,
which registers each ``{nodes, rels}`` it holds.  It is *not* written to the graph on every read tool call
because read tools open the directory store read-only (no writer lease, so they never contend with a human
running ``crosswalk review``).  Three fallbacks make the checker work in a fresh process (the CLI, a
restarted MCP server) and keep it honest:

1. inline receipts in the answer (``paths`` entries ``{id, nodes, rels}``) count only if the id equals the
   hash of the nodes and rels, so an id cannot be made to mean something else;
2. ``(:Path {id, nodes, rels})`` nodes persisted by an earlier :func:`persist` (the audit trail);
3. :func:`discover`: enumerate every path *shape* any read command can cite over the whole graph
   (``queries/all_paths.cypher``: requirement-control-evidence, inherited, evidence-control, audit-evidence,
   person-control, proposal and decision paths, tracker rows; plus the absence receipts and the long suggest
   "family" paths) with no date, adoption or approval filter, and register all of it.  The result does not
   depend on which cutoff, audit or ``--days`` a command was called with, so an id from ``crosswalk blast
   --until X`` or ``--audit AUD-171`` resolves in a fresh process.

Only a path that no tool could ever have produced (a fabricated id) stays unknown.

Writes: :func:`persist` stores ``(:Answer)-[:HAS_CLAIM]->(:Claim)-[:CITES]->(:Path)`` through a writer the
caller opened with :func:`crosswalk.proposals.open_writer` (the single writer lease rules apply).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Iterable

import relate

from crosswalk import queries as Q
from crosswalk.coverage import read_as_of
from crosswalk.paths import absence_path, id_of_canonical, make_path, path_id

SYMBOL = {"verified": "✔", "partial": "⚠", "failed": "✖"}
PATH_STATUS = {"valid": "ok", "proposed_mapping": "warn"}
COVERAGE_KINDS = frozenset({"coverage", "covered"})
_NODE_REF = re.compile(r"^[A-Za-z][A-Za-z]*:.+")
_LABEL_PREFIX = re.compile(r"\b(?:Control|Evidence|Requirement|Proposal|Policy|System|Person|Framework|Family):(?=\S)")
_PATH_ID = re.compile(r"^P-[0-9a-f]{12}$")
FAIL_ORDER = ("broken_structure", "expired_evidence", "not_adopted", "rejected_mapping", "proposed_mapping")


class ClaimsError(ValueError):
    """The answer JSON itself is malformed (not a claim failure)."""


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


def _is_path(d: Any) -> bool:
    n, r = d.get("nodes"), d.get("rels")
    return (isinstance(n, list) and isinstance(r, list) and bool(r) and len(n) == len(r) + 1
            and all(isinstance(x, str) and _NODE_REF.match(x) for x in n) and all(isinstance(x, str) for x in r))


class PathRegistry:
    """In-process ``path id -> {id, nodes, rels, source}``; thread safe."""

    def __init__(self) -> None:
        self._paths: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.discovered = False
        self._searched: set[str] = set()  # ids the last full discovery could not find

    def __len__(self) -> int:
        return len(self._paths)

    def __contains__(self, pid: str) -> bool:
        return pid in self._paths

    def register(self, nodes: list[str], rels: list[str], source: str = "tool") -> str:
        p = make_path(list(nodes), list(rels))
        with self._lock:
            self._paths.setdefault(p["id"], {**p, "source": source})
        return p["id"]

    def register_result(self, obj: Any, source: str = "tool") -> int:
        """Register every path found anywhere inside a tool result (dicts and lists, recursively)."""
        found = 0
        stack = [obj]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if _is_path(x):
                    try:
                        self.register(x["nodes"], x["rels"], source)
                        found += 1
                    except ValueError:
                        pass
                    continue
                stack.extend(x.values())
            elif isinstance(x, (list, tuple)):
                stack.extend(x)
        return found

    def get(self, pid: str) -> dict | None:
        with self._lock:
            return self._paths.get(pid)

    def resolve(self, conn: relate.Connection, pid: str, inline: dict[str, dict] | None = None) -> dict | None:
        """Path for ``pid``: memory, then honest inline receipts, then ``:Path`` nodes, then discovery."""
        got = self.get(pid)
        if got:
            return got
        if inline and pid in inline:
            return inline[pid]
        if _PATH_ID.match(pid):
            rows = conn.execute("MATCH (p:Path {id: $id}) RETURN p.nodes AS nodes, p.rels AS rels", {"id": pid}).fetchall()
            if rows and rows[0]["nodes"]:
                self.register(list(rows[0]["nodes"]), list(rows[0]["rels"]), "graph")
                return self.get(pid)
            if not self.discovered or pid not in self._searched:
                discover(conn, self, wanted={pid})
                return self.get(pid)
        return None

    def prepare(self, conn: relate.Connection, ids: Iterable[str], inline: dict[str, dict] | None = None) -> None:
        """Resolve ``ids`` in one go: only if some are unknown does the graph get enumerated (once, not per id)."""
        inline = inline or {}
        unknown = {i for i in ids if _PATH_ID.match(i) and i not in self and i not in inline}
        if unknown:
            for pid in sorted(unknown):  # honest earlier receipts persisted by `check --persist`
                rows = conn.execute("MATCH (p:Path {id: $id}) RETURN p.nodes AS nodes, p.rels AS rels",
                                    {"id": pid}).fetchall()
                if rows and rows[0]["nodes"]:
                    self.register(list(rows[0]["nodes"]), list(rows[0]["rels"]), "graph")
            unknown = {i for i in unknown if i not in self}
        if unknown:
            discover(conn, self, wanted=unknown)


REGISTRY = PathRegistry()  # the default, shared by the MCP server tools


def _family_paths(conn: relate.Connection, wanted: set[str], registry: PathRegistry) -> int:
    """Register the suggest "family" paths whose id is in ``wanted`` (there are ~160 000 of them: they are
    hashed one by one and only the hits are kept).

    ``Control <-MANDATES- Policy -MANDATES-> Control -SATISFIES-> Requirement -PART_OF-> Family <-PART_OF-
    Requirement``: a sibling control of the same policy already satisfies a requirement of the candidate's family.
    """
    vias = [dict(r) for r in conn.execute(
        "MATCH (c:Control)<-[:MANDATES]-(p:Policy)-[:MANDATES]->(o:Control)-[:SATISFIES]->(q:Requirement)"
        "-[:PART_OF]->(f:Family) WHERE o.id <> c.id RETURN c.id AS c, p.id AS p, o.id AS o, q.id AS q, f.id AS f"
    ).fetchall()]
    members: dict[str, list[str]] = {}
    for r in conn.execute("MATCH (x:Requirement)-[:PART_OF]->(f:Family) RETURN f.id AS f, x.id AS x").fetchall():
        members.setdefault(r["f"], []).append(r["x"])
    found = 0
    rels = ["MANDATES<-", "MANDATES", "SATISFIES", "PART_OF", "PART_OF<-"]
    for v in vias:
        head = (f"Control:{v['c']}|MANDATES<-|Policy:{v['p']}|MANDATES|Control:{v['o']}|SATISFIES|"
                f"Requirement:{v['q']}|PART_OF|Family:{v['f']}|PART_OF<-|Requirement:")
        for x in members.get(v["f"], ()):
            if id_of_canonical(head + x) in wanted:
                nodes = [f"Control:{v['c']}", f"Policy:{v['p']}", f"Control:{v['o']}", f"Requirement:{v['q']}",
                         f"Family:{v['f']}", f"Requirement:{x}"]
                registry.register(nodes, rels, "discover")
                found += 1
    return found


def discover(conn: relate.Connection, registry: PathRegistry | None = None, wanted: Iterable[str] | None = None) -> int:
    """Register every path any read command can produce, whatever cutoff, audit or date it was called with;
    returns how many paths the registry knows.

    The shapes come from ``queries/all_paths.cypher`` (a superset: no validity filter), the absence receipts
    (an adopted control with no ``OWNS`` / no ``PROVES``; a tracker requirement with no ``SATISFIES``) and, as a
    safety net, a re-run of the question set.  ``wanted`` (path ids a caller is looking for) additionally
    searches the very large set of suggest "family" paths and keeps only the ids asked for.
    """
    registry = registry if registry is not None else REGISTRY
    for r in Q.run(conn, "all_paths"):
        try:
            registry.register(r["nodes"], r["rels"], "discover")
        except ValueError:
            pass
    for r in conn.execute("MATCH (c:Control) RETURN c.id AS id").fetchall():
        registry.register(*_nr(absence_path("Control", r["id"], "OWNS", "Person", reversed_=True)), "discover")
        registry.register(*_nr(absence_path("Control", r["id"], "PROVES", "Evidence", reversed_=True)), "discover")
    for r in conn.execute("MATCH (t:TrackerRow) RETURN t.control AS control, t.requirements AS reqs").fetchall():
        for q in r["reqs"] or []:
            registry.register(*_nr(absence_path("Control", r["control"], "SATISFIES", "Requirement", q)), "discover")
    at = read_as_of(conn)
    for fw in Q.FRAMEWORKS:  # safety net: whatever the question set returns is known too
        registry.register_result(Q.coverage(conn, fw, at), "discover")
    registry.register_result(Q.blast(conn, until="2100-01-01", as_of=at), "discover")
    registry.register_result(Q.owner_risk(conn, at), "discover")
    registry.register_result(Q.evidence(conn, as_of=at), "discover")
    registry.register_result(Q.stale(conn, at), "discover")
    registry.discovered = True
    want = {w for w in (wanted or ()) if w not in registry}
    if want:
        _family_paths(conn, want, registry)
    registry._searched = {w for w in want if w not in registry}
    return len(registry)


def _nr(p: dict) -> tuple[list[str], list[str]]:
    return p["nodes"], p["rels"]


# --------------------------------------------------------------------------
# path verdicts
# --------------------------------------------------------------------------


def humanise(text: str) -> str:
    """Drop the ``Label:`` prefixes of node references: ``Evidence:EV-044 expired 2026-12-01`` -> ``EV-044 expired ...``."""
    return _LABEL_PREFIX.sub("", text)


def chain(nodes: Iterable[str], rels: Iterable[str]) -> str:
    """Readable form of a path: ``800-171:03.05.03 <-SATISFIES- CTRL-REAP-6 <-PROVES- EV-044``."""
    full = list(nodes)
    nodes = [n.partition(":")[2] or n for n in nodes]
    out = [nodes[0]]
    for rel, node, ref in zip(rels, nodes[1:], full[1:]):
        if rel.startswith("NO_"):  # an absence receipt: "CTRL-X has no OWNS from any Person"
            kind = rel[len("NO_"):].removesuffix("<-")
            other = f"any {ref.partition(':')[0]}" if node == "*" else node
            out += [f"has no {kind} {'from' if rel.endswith('<-') else 'to'}", other]
        else:
            out += [f"<-{rel[:-2]}-" if rel.endswith("<-") else f"-{rel}->", node]
    return " ".join(out)


def _classify(exists: bool, valid: bool, problems: list[str]) -> tuple[str, str, list[str]]:
    """(code, reason, humanised problems) from check_path's ``problems``."""
    if valid:
        return "valid", "valid", []
    human = [humanise(p) for p in problems]
    codes = set()
    for p in human:
        if p.startswith("no ") and " relationship from " in p:
            codes.add("broken_structure")
        elif " expired " in p:
            codes.add("expired_evidence")
        elif p.endswith("is not adopted"):
            codes.add("not_adopted")
        elif " was rejected (" in p:
            codes.add("rejected_mapping")
        elif "not approved" in p:
            codes.add("proposed_mapping")
        else:
            codes.add("broken_structure")
    if not exists:
        codes.add("broken_structure")
    code = next(c for c in FAIL_ORDER if c in codes)
    reasons = []
    for p in human:
        if p.startswith("no ") and " relationship from " in p:
            p = "broken path: " + p
        elif p.endswith("is not adopted"):
            p = "control " + p
        reasons.append(p)
    if not reasons:
        reasons = ["path does not exist in the graph"]
    return code, "; ".join(dict.fromkeys(reasons)), human


def check_one(conn: relate.Connection, pid: str, registry: PathRegistry, as_of: str,
              inline: dict[str, dict] | None = None) -> dict:
    """Verdict for one cited path id."""
    p = registry.resolve(conn, pid, inline)
    if p is None:
        return {"id": pid, "status": "fail", "code": "unknown_path", "valid": False, "exists": False,
                "reason": "uncited/unknown path: no tool returned this path id and it cannot be rebuilt "
                          "from the graph", "problems": [], "chain": None, "nodes": None, "rels": None,
                "source": None}
    res = Q.check_path(conn, p["nodes"], p["rels"], as_of)
    code, reason, problems = _classify(res["exists"], res["valid"], res["problems"])
    return {"id": pid, "status": PATH_STATUS.get(code, "fail"), "code": code, "valid": res["valid"],
            "exists": res["exists"], "reason": reason, "problems": problems,
            "chain": chain(p["nodes"], p["rels"]), "nodes": p["nodes"], "rels": p["rels"],
            "source": p.get("source")}


# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------


def _ids(claim: dict) -> list[str]:
    raw = claim.get("path_ids")
    if raw is None:
        raw = claim.get("paths", claim.get("path_id"))
    if raw is None:
        return []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    out = []
    for x in raw:
        x = x.get("id") if isinstance(x, dict) else x
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return list(dict.fromkeys(out))


def _inline_receipts(answer: dict) -> dict[str, dict]:
    """Paths an answer carries itself; kept only when the id really is the hash of nodes + rels."""
    out: dict[str, dict] = {}
    raw = answer.get("paths") or answer.get("receipts") or []
    items = raw.values() if isinstance(raw, dict) else raw
    for x in items:
        if isinstance(x, dict) and _is_path(x) and isinstance(x.get("id"), str):
            try:
                if path_id(x["nodes"], x["rels"]) == x["id"]:
                    out[x["id"]] = {"id": x["id"], "nodes": list(x["nodes"]), "rels": list(x["rels"]),
                                    "source": "inline"}
            except ValueError:
                pass
    return out


def _claim_verdict(paths: list[dict]) -> tuple[str, str]:
    if not paths:
        return "failed", "no receipt: the claim cites no path id"
    statuses = [p["status"] for p in paths]
    if all(s == "ok" for s in statuses):
        return "verified", "every cited path re-ran valid"
    if "ok" not in statuses and "fail" in statuses:
        return "failed", "; ".join(p["reason"] for p in paths if p["status"] != "ok")
    return "partial", "; ".join(p["reason"] for p in paths if p["status"] != "ok")


def check_claims(conn: relate.Connection, answer: dict | str, registry: PathRegistry | None = None,
                 as_of: str | None = None) -> dict:
    """Re-run every cited path of ``answer`` and return the checked answer (read-only, deterministic).

    Result: ``{question, agent, as_of, counts: {claims, verified, partial, failed, paths, paths_ok},
    summary, claims: [{index, text, kind, verdict, symbol, reason, reasons, codes, path_ids, paths: [...]}]}``.
    Nothing in it depends on the clock, so a replay gives byte-identical output.
    """
    registry = registry if registry is not None else REGISTRY
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except json.JSONDecodeError as exc:
            raise ClaimsError(f"answer is not valid JSON: {exc}") from None
    if not isinstance(answer, dict) or not isinstance(answer.get("claims"), list):
        raise ClaimsError("answer must be an object with a 'claims' list")
    at = str(as_of) if as_of else read_as_of(conn)
    inline = _inline_receipts(answer)
    registry.prepare(conn, [i for c in answer["claims"] if isinstance(c, dict) for i in _ids(c)], inline)
    cache: dict[str, dict] = {}
    claims = []
    for i, c in enumerate(answer["claims"], 1):
        if isinstance(c, str):
            c = {"text": c}
        if not isinstance(c, dict):
            raise ClaimsError(f"claim {i} must be an object with 'text' and 'path_ids'")
        ids = _ids(c)
        paths = []
        for pid in ids:
            if pid not in cache:
                cache[pid] = check_one(conn, pid, registry, at, inline)
            v = cache[pid]
            if (c.get("kind") in COVERAGE_KINDS and v["status"] == "ok" and v["nodes"][0].startswith("Requirement:")
                    and not any(n.startswith("Evidence:") for n in v["nodes"])):
                # check_path judges only what is on the path; a coverage claim needs evidence on it
                v = {**v, "status": "fail", "code": "no_evidence", "valid": False,
                     "reason": "path has no evidence: a requirement-control mapping alone does not show coverage"}
            paths.append(v)
        verdict, why = _claim_verdict(paths)
        reasons = [f"{p['id']}: {p['reason']}" for p in paths if p["status"] != "ok"] or (
            [why] if verdict == "failed" else [])
        claims.append({
            "index": i, "text": str(c.get("text", "")).strip(), "kind": c.get("kind"),
            "verdict": verdict, "symbol": SYMBOL[verdict], "verified": verdict == "verified",
            "reason": why, "reasons": reasons,
            "codes": sorted({p["code"] for p in paths if p["status"] != "ok"} or ({"no_receipt"} if not paths else set())),
            "path_ids": ids, "paths": paths,
        })
    counts = {"claims": len(claims),
              "verified": sum(c["verdict"] == "verified" for c in claims),
              "partial": sum(c["verdict"] == "partial" for c in claims),
              "failed": sum(c["verdict"] == "failed" for c in claims),
              "paths": len(cache),
              "paths_ok": len({p["id"] for c in claims for p in c["paths"] if p["status"] == "ok"})}
    summary = f"{counts['verified']}/{counts['claims']} claims verified"
    extra = [f"{counts[k]} {w}" for k, w in (("partial", "partial"), ("failed", "failed")) if counts[k]]
    if extra:
        summary += " (" + ", ".join(extra) + ")"
    return {"question": answer.get("question"), "agent": answer.get("agent"), "as_of": at, "counts": counts,
            "summary": summary, "claims": claims}


# --------------------------------------------------------------------------
# persistence: (:Answer)-[:HAS_CLAIM]->(:Claim)-[:CITES]->(:Path)
# --------------------------------------------------------------------------


def persist(conn: relate.Connection, checked: dict, retries: int = 2) -> dict:
    """Store a checked answer in the graph (``conn`` is a writer from ``proposals.open_writer``).

    One transaction: ``(:Answer {id, question, agent, as_of, claims, verified, partial, failed})``
    ``-[:HAS_CLAIM]->(:Claim {id, text, verdict, verified, reason, reasons, unknown_paths})``
    ``-[:CITES]->(:Path {id, nodes, rels})``.  ``Path`` nodes are merged by id.  Returns
    ``{"answer": id, "bookmark": ...}``.
    """
    from crosswalk.proposals import _rollback, is_retryable, next_id  # local: proposals imports verify/build

    attempt = 0
    while True:
        attempt += 1
        try:
            conn.autocommit = False
            aid = next_id(conn, "Answer", "ANS")
            n = checked["counts"]
            conn.execute(
                "CREATE (a:Answer {id: $id, question: $q, agent: $ag, as_of: date($at), claims: $n, "
                "verified: $v, partial: $p, failed: $f, summary: $s})",
                {"id": aid, "q": checked.get("question") or "", "ag": checked.get("agent") or "", "at": checked["as_of"],
                 "n": n["claims"], "v": n["verified"], "p": n["partial"], "f": n["failed"], "s": checked["summary"]})
            for c in checked["claims"]:
                cid = f"{aid}-C{c['index']}"
                unknown = [p["id"] for p in c["paths"] if p["code"] == "unknown_path"]
                conn.execute(
                    "MATCH (a:Answer {id: $a}) CREATE (c:Claim {id: $id, text: $t, verdict: $vd, verified: $v, "
                    "reason: $r, reasons: $rs, unknown_paths: $u, checked_at: date($at)}) CREATE (a)-[:HAS_CLAIM]->(c)",
                    {"a": aid, "id": cid, "t": c["text"], "vd": c["verdict"], "v": c["verified"], "r": c["reason"],
                     "rs": c["reasons"], "u": unknown, "at": checked["as_of"]})
                for p in c["paths"]:
                    if p["code"] == "unknown_path":
                        continue
                    conn.execute(
                        "MATCH (c:Claim {id: $c}) MERGE (p:Path {id: $p}) "
                        "ON CREATE SET p.nodes = $nodes, p.rels = $rels "
                        "CREATE (c)-[:CITES {status: $st, code: $code, reason: $why}]->(p)",
                        {"c": cid, "p": p["id"], "nodes": p["nodes"], "rels": p["rels"], "st": p["status"],
                         "code": p["code"], "why": p["reason"]})
            return {"answer": aid, "bookmark": conn.commit()}
        except Exception as exc:
            _rollback(conn)
            if is_retryable(exc) and attempt <= retries:
                continue
            raise


# --------------------------------------------------------------------------
# the corrected answer
# --------------------------------------------------------------------------

_EXPIRED = re.compile(r"(\S+) expired (\d{4}-\d{2}-\d{2})")
_PROPOSAL = re.compile(r"\((PR-\d+)\)")


def _owner_names(conn: relate.Connection, evidence: str) -> list[str]:
    return [r["n"] for r in conn.execute(
        "MATCH (p:Person)-[:OWNS]->(:Evidence {id: $e}) RETURN p.name AS n ORDER BY n", {"e": evidence}).fetchall()]


def next_actions(conn: relate.Connection, checked: dict) -> list[dict]:
    """What a human should do about the failed or partial claims, derived from the failing paths."""
    actions: dict[tuple, dict] = {}
    for c in checked["claims"]:
        if not c["paths"] and c["verdict"] == "failed":
            actions.setdefault(("cite", c["index"]), {"action": "cite", "claim": c["index"],
                                                      "text": "attach a path id to: " + c["text"]})
        for p in c["paths"]:
            if p["status"] == "ok":
                continue
            if p["code"] == "unknown_path":
                actions.setdefault(("drop", p["id"]), {"action": "drop", "path": p["id"],
                                                       "text": f"drop the unknown path {p['id']}"})
            for prob in p["problems"]:
                m = _EXPIRED.search(prob)
                if m:
                    ev = m.group(1)
                    actions.setdefault(("renew", ev), {"action": "renew_evidence", "evidence": ev,
                                                       "expired": m.group(2), "owners": _owner_names(conn, ev)})
                m = _PROPOSAL.search(prob)
                if m and "not approved" in prob:
                    actions.setdefault(("review", m.group(1)), {"action": "review_proposal", "proposal": m.group(1)})
                if "is not adopted" in prob:
                    ctrl = prob.split(" is not adopted")[0]
                    actions.setdefault(("adopt", ctrl), {"action": "adopt_control", "control": ctrl,
                                                         "text": f"adopt or stop citing {ctrl}"})
            if p["code"] == "no_evidence":
                actions.setdefault(("collect", p["id"]), {"action": "collect_evidence", "path": p["id"],
                                                          "text": f"collect evidence for {p['chain']}"})
            if p["code"] == "broken_structure":
                actions.setdefault(("fix", p["id"]), {"action": "fix_path", "path": p["id"],
                                                      "text": f"re-run the query for {p['id']}: it no longer exists"})
    order = {"renew_evidence": 0, "review_proposal": 1}
    return sorted(actions.values(), key=lambda a: (order.get(a["action"], 2), json.dumps(a, sort_keys=True)))


def corrected_answer(conn: relate.Connection, checked: dict, drafted: dict[str, str] | None = None) -> dict:
    """``{"text", "actions"}``: the answer after the check.  ``drafted`` maps evidence id -> proposal id
    of an evidence request already drafted (it adds ``request drafted`` to the renewal)."""
    drafted = drafted or {}
    c = checked["counts"]
    if c["claims"] and c["verified"] == c["claims"]:
        return {"text": f"All {c['claims']} claims verified.", "actions": []}
    actions = next_actions(conn, checked)
    coverage_only = all(x["kind"] in (None, "coverage", "covered") for x in checked["claims"] if x["verdict"] != "verified")
    parts = []
    for a in actions:
        if a["action"] == "renew_evidence":
            who = ", ".join(a["owners"]) or "no owner on record"
            note = ", request drafted" if a["evidence"] in drafted else ""
            parts.append(f"Renew {a['evidence']} (owner {who}{note})")
        elif a["action"] == "review_proposal":
            parts.append(f"review {a['proposal']}")
        else:
            parts.append(a["text"])
    head = "Not covered." if coverage_only else "Not verified."
    if not parts:
        return {"text": head, "actions": actions}
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return {"text": f"{head} {body}.", "actions": actions}


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render_lines(checked: dict) -> list[str]:
    """Plain-text lines: one per claim, then one indented line per not-ok path with its reason."""
    lines = []
    for c in checked["claims"]:
        lines.append(f"{c['symbol']} {c['text']}")
        if not c["paths"]:
            lines.append(f"    {c['reason']}")
        for p in c["paths"]:
            mark = {"ok": "✔", "warn": "⚠", "fail": "✖"}[p["status"]]
            lines.append(f"    {mark} {p['id']}  {p['reason'] if p['status'] != 'ok' else p['chain']}")
    lines.append(checked["summary"])
    return lines


def load_answer(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ClaimsError(f"no such file: {path}") from None
    except json.JSONDecodeError as exc:
        raise ClaimsError(f"{path} is not valid JSON: {exc}") from None
