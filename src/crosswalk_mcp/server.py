"""crosswalk-mcp: the narrow MCP server (stdio) that agents use to read the compliance graph and to propose.

Run it with ``python -m crosswalk_mcp.server`` (or the ``crosswalk-mcp`` console script).  The store is
``$CROSSWALK_STORE`` (default ``data/crosswalk``, relative to the repo root).

Tools
-----
read   ``coverage(framework|audit)``  ``adopt(framework)``  ``blast(days|until|audit)``
       ``suggest(control, framework, k, method)``  ``explain(requirement)``  ``owners()``  ``reuse(top)``
       ``decisions(about?)``  ``stale()``  ``evidence(audit?, status?, until?)``  ``check_claims(answer)``
write  ``propose_mapping``  ``propose_evidence_request``  ``propose_status``: they ONLY create
       ``:Proposal`` nodes (``crosswalk.proposals.create_proposal``, verified in the same transaction).
       Nothing here can create ``SATISFIES``, set a status or decide a proposal: only a human running
       ``crosswalk review`` can.

Every read result is compact (lists capped, totals included) and carries **path ids**.  Cite them in
the answer and send the answer to ``check_claims``, which re-runs every path and says which claims are
verified, partial or failed (see :mod:`crosswalk.claims`).

Store strategy (the directory store has ONE writer lease)
---------------------------------------------------------
* every read tool opens the store **read-only for that one call** and closes it.  A read-only handle is a
  snapshot taken at open, and it never takes the lease, so reads run beside a human's ``crosswalk review``
  or another writer and always see everything committed so far;
* a write tool (``propose_*`` and the persistence step of ``check_claims``) opens the writer **only for
  that call**, waits up to ``$CROSSWALK_WRITE_WAIT`` seconds (default 10) for a competing writer to
  release the lease, writes one transaction and closes (which checkpoints).  The lease is therefore held
  for milliseconds and agents never fight over it;
* one process-wide path registry (:data:`crosswalk.claims.REGISTRY`) remembers every path the read
  tools returned, so ``check_claims`` can re-run them.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

os.environ.setdefault("DO_NOT_TRACK", "1")

import relate  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from crosswalk import claims as C  # noqa: E402
from crosswalk import coverage as cov  # noqa: E402
from crosswalk import proposals as P  # noqa: E402
from crosswalk import queries as Q  # noqa: E402
from crosswalk import review as R  # noqa: E402
from crosswalk.build import is_locked_error, resolve_store  # noqa: E402

DEFAULT_STORE = "data/crosswalk"
CAP = 25  # default cap on list sizes in read results

mcp = FastMCP(
    "crosswalk",
    instructions=(
        "Crosswalk: a compliance graph (controls, evidence, requirements of NIST 800-53, 800-171 and CSF). "
        "Read tools return results with path ids (P-...).  Every claim in your answer must cite the path ids "
        "that prove it (mark claims that something is covered with kind 'coverage': they need a path that "
        "ends in evidence); call check_claims on the answer before you give it to a person and correct or drop "
        "what fails.  Use explain(requirement) to get citable paths for any requirement, including expired "
        "ones and pending proposals.  stale() lists controls the legacy tracker marks Compliant that the graph "
        "contradicts; evidence(audit, status) lists expired / expiring evidence per audit.  You can only PROPOSE changes (propose_mapping, propose_status, "
        "propose_evidence_request); a human approves.  Read decisions(about) before proposing: a rejected "
        "mapping must not be proposed again."
    ),
)


# --------------------------------------------------------------------------
# store plumbing
# --------------------------------------------------------------------------


def store_path() -> str:
    return os.environ.get("CROSSWALK_STORE") or DEFAULT_STORE


@contextmanager
def _reader() -> Iterator[relate.Connection]:
    """A read-only snapshot of the store for the duration of one call."""
    path = resolve_store(store_path())
    if not (path / "manifest.json").exists():
        raise RuntimeError(f"no store at {path}; run `crosswalk build` first (or set CROSSWALK_STORE)")
    try:
        conn = cov.open_read_only(store_path())
    except relate.OperationalError as exc:
        raise RuntimeError("the store is locked by another process; try again" if is_locked_error(exc) else str(exc))
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _writer() -> Iterator[relate.Connection]:
    """The single writer for the duration of one call (waits for a competing writer, then releases)."""
    wait = float(os.environ.get("CROSSWALK_WRITE_WAIT", "10"))
    try:
        conn = P.open_writer(store_path(), wait=wait)
    except relate.OperationalError as exc:
        if is_locked_error(exc):
            raise RuntimeError(f"another writer held the store for more than {wait:g}s; nothing was written, "
                               f"retry the call")
        raise
    try:
        yield conn
    finally:
        conn.close()


def _paths(result: Any, source: str) -> None:
    C.REGISTRY.register_result(result, source)


def _ids(paths: list[dict], n: int = 1) -> list[str]:
    return [p["id"] for p in paths[:n]]


def _cap(rows: list, n: int | None) -> tuple[list, dict]:
    n = CAP if n is None else max(1, int(n))
    return rows[:n], ({"shown": n, "total": len(rows)} if len(rows) > n else {})


# --------------------------------------------------------------------------
# read tools
# --------------------------------------------------------------------------


@mcp.tool()
def coverage(framework: str | None = None, audit: str | None = None) -> dict:
    """Coverage of a framework ('800-171', '800-53', 'CSF') or of an audit's scope (e.g. 'AUD-171'), as of
    the store's date: totals plus capped lists of gaps, covered and inherited requirements with path ids."""
    with _reader() as conn:
        res = Q.coverage(conn, framework, None, audit)
    _paths(res, "coverage")
    rows = res["requirements"]
    by = {s: [r for r in rows if r["status"] == s] for s in ("gap", "covered", "inherited")}
    out: dict[str, Any] = {k: res[k] for k in ("framework", "as_of", "total", "covered", "inherited", "gaps")}
    if res.get("audit"):
        out["audit"] = res["audit"]
    out["covered_pct"] = round(100 * res["covered"] / res["total"]) if res["total"] else 0
    out["covered_or_inherited_pct"] = round(100 * (res["covered"] + res["inherited"]) / res["total"]) if res["total"] else 0
    trunc = {}
    for key, name, fn in (
        ("gap", "gap_list", lambda r: {"id": r["id"], "title": r["title"]}),
        ("covered", "covered_list", lambda r: {"id": r["id"], "controls": r["controls"],
                                              "evidence": r["evidence"][:3], "path_ids": _ids(r["paths"], 2)}),
        ("inherited", "inherited_list", lambda r: {"id": r["id"], "via": r["via"][:3], "path_ids": _ids(r["paths"], 2)}),
    ):
        shown, t = _cap(by[key], CAP)
        out[name] = [fn(r) for r in shown]
        if t:
            trunc[name] = t
    if trunc:
        out["truncated"] = trunc
    out["hint"] = "explain(requirement) gives every citable path (including expired and proposed) for one requirement"
    return out


@mcp.tool()
def adopt(framework: str) -> dict:
    """Adopting a framework ('800-171' or 'CSF'): which of its requirements are already met through the
    crosswalk (1 hop) from covered 800-53 mappings.  Capped list with path ids."""
    with _reader() as conn:
        res = Q.adopt(conn, framework)
    _paths(res, "adopt")
    shown, t = _cap(res["inherited"], CAP)
    out = {"framework": res["framework"], "as_of": res["as_of"], "active_requirements": res["active_requirements"],
           "inherited_count": res["inherited_count"],
           "inherited": [{"requirement": i["requirement"], "title": i["title"],
                          "via": [v["neighbour"] for v in i["via"]],
                          "controls": sorted({c["control"] for v in i["via"] for c in v["controls"]}),
                          "path_ids": _ids(i["paths"], 2)} for i in shown]}
    if t:
        out["truncated"] = {"inherited": t}
    return out


@mcp.tool()
def blast(days: int = 30, until: str | None = None, audit: str | None = None) -> dict:
    """Blast radius of expiring evidence: what loses direct coverage if evidence expiring within `days` of
    the store's date (or on/before `until`, or before audit `audit`) is not renewed.  Path ids included."""
    with _reader() as conn:
        res = Q.blast(conn, days, until, audit)
    _paths(res, "blast")
    ev, te = _cap(res["expiring_evidence"], CAP)
    br, tb = _cap(res["broken_requirements"], CAP)
    out = {"as_of": res["as_of"], "cutoff": res["cutoff"], "window_days": res["window_days"],
           "expiring_evidence": [{"evidence": e["evidence"], "expires_at": e["expires_at"],
                                  "controls_left_without_valid_evidence": e["controls_left_without_valid_evidence"],
                                  "requested_by": e["requested_by"], "path_ids": _ids(e["paths"], 2)} for e in ev],
           "broken_counts": res["broken_counts"], "broken_and_not_inherited": res["broken_and_not_inherited"],
           "broken_requirements": [{"requirement": b["requirement"], "controls_lost": b["controls_lost"],
                                    "evidence_lost": b["evidence_lost"], "still_inherited": b["still_inherited"],
                                    "path_ids": _ids(b["paths"], 2)} for b in br],
           "affected_audits": [{"audit": a["audit"], "date": a["date"], "reasons": a["reasons"],
                                "path_ids": _ids(a["paths"], 2)} for a in res["affected_audits"]]}
    trunc = {k: v for k, v in (("expiring_evidence", te), ("broken_requirements", tb)) if v}
    if trunc:
        out["truncated"] = trunc
    return out


@mcp.tool()
def suggest(control: str, framework: str = "800-53", k: int = 5, method: str = "hybrid+graph") -> dict:
    """Candidate requirements of `framework` that `control` probably satisfies (method: fulltext, vector,
    hybrid or hybrid+graph).  Suggestions are NOT mappings: use propose_mapping, after reading decisions()."""
    from crosswalk import suggest as S

    k = max(1, min(int(k), 20))
    with _reader() as conn:
        try:
            rows = S.suggest(conn, control, cov.normalise_framework(framework), k=k, method=method)
        except S.SuggestError as exc:
            raise ValueError(str(exc))
    _paths(rows, "suggest")
    out = []
    for r in rows:
        g = (r.get("signals") or {}).get("graph") or {}
        item = {"requirement": r["id"], "title": r["title"], "score": round(r["score"], 4),
                "graph_signals": sorted(g), "path_ids": [p["id"] for p in r["paths"]][:3]}
        if "rejected" in g:
            item["previously_rejected"] = {k2: g["rejected"].get(k2) for k2 in ("proposal", "by", "reason")}
        out.append(item)
    return {"control": control, "framework": cov.normalise_framework(framework), "method": method,
            "suggestions": out, "note": "candidates only; nothing is mapped until a human approves a proposal"}


@mcp.tool()
def explain(requirement: str) -> dict:
    """Why a requirement ('03.05.03', '800-171:03.05.03', 'AC-2(1)') is covered, inherited or a gap: every
    control and evidence path with dates and validity (including expired ones), inherited paths and any
    pending proposals as citable proposed paths."""
    with _reader() as conn:
        res = Q.explain(conn, Q.resolve_requirement(conn, requirement))
    _paths(res, "explain")
    status = "covered" if res["covered_direct"] else ("inherited" if res["inherited"] else "gap")
    inh, ti = _cap(res["inherited_paths"], 8)
    out = {
        "requirement": res["requirement"], "framework": res["framework"], "title": res["title"],
        "as_of": res["as_of"], "status": status, "inherited_via": res["inherited_via"],
        "paths": [{"path_id": p["path_id"], "chain": C.chain(p["nodes"], p["rels"]), "control": p["control"],
                   "control_status": p["control_status"], "evidence": p["evidence"], "valid": p["valid"],
                   "expires_at": p.get("expires_at"), "owners": p["control_owners"]} for p in res["paths"]],
        "inherited_paths": [{"path_id": p["id"], "neighbour": p["neighbour"], "control": p["control"],
                             "evidence": p["evidence"], "expires_at": p["expires_at"]} for p in inh],
        "proposals": [{"proposal": d["proposal"], "control": d["control"], "status": d["status"],
                       "decision": d["decision"], "path_id": d["path_id"]} for d in res["proposals"]],
        "note": "a path with valid=false or a proposal is NOT coverage: cite it only to say it fails",
    }
    if ti:
        out["truncated"] = {"inherited_paths": ti}
    return out


@mcp.tool()
def owners() -> dict:
    """Owner risk: who solely owns how many controls, what depends on them, and controls with no owner."""
    with _reader() as conn:
        res = Q.owner_risk(conn)
    _paths(res, "owners")
    ranking, t = _cap(res["sole_owner_ranking"], 10)
    out = {"sole_owner_ranking": [
        {"person": r["person"], "name": res["people"][r["person"]]["name"], "sole_owned_count": r["sole_owned_count"],
         "controls_touching_high_systems": r["controls_touching_high_systems"],
         "controls": res["people"][r["person"]]["controls_solely_owned"][:10],
         "requirements_solely_dependent": len(res["people"][r["person"]]["requirements_solely_dependent"]),
         "audits_affected": res["people"][r["person"]]["audits_affected"],
         "path_ids": _ids(res["people"][r["person"]]["paths"], 3)} for r in ranking],
        "unowned_controls": res["unowned_controls"],
        "unowned": [{"control": d["control"], "title": d["title"], "status": d["status"],
                     "path_ids": _ids(d["paths"], 1)} for d in res["unowned_detail"]],
        "note": "an 'unowned' path_id is an absence receipt: the control is adopted and no person OWNS it"}
    if t:
        out["truncated"] = {"sole_owner_ranking": t}
    return out


@mcp.tool()
def reuse(top: int = 5) -> dict:
    """Evidence reuse: the valid evidence items backing the most requirements across frameworks."""
    top = max(1, min(int(top), 20))
    with _reader() as conn:
        res = Q.reuse(conn, top)
    _paths(res, "reuse")
    return {"top": [{"rank": r["rank"], "evidence": r["evidence"], "expires_at": r["expires_at"],
                     "controls": r["controls"], "direct_count": r["direct_count"],
                     "frameworks_reached": r["frameworks_reached"], "reach_count": r["reach_count"],
                     "path_ids": _ids(r["paths"], 3)} for r in res]}


@mcp.tool()
def decisions(about: str | None = None) -> dict:
    """Past human approvals and rejections with their reasons (read this before proposing), optionally only
    those about a control, requirement, evidence or person id; plus any pending proposals about it as
    citable proposed paths."""
    with _reader() as conn:
        rows = R.decisions(conn, about)
        pend: list[dict] = []
        if about:
            pend = Q.proposed_paths(conn, control=about, status="pending")
            try:
                pend += Q.proposed_paths(conn, requirement=Q.resolve_requirement(conn, about), status="pending")
            except LookupError:
                pass
        else:
            pend = Q.proposed_paths(conn, status="pending")
    _paths(pend, "decisions")
    _paths(rows, "decisions")
    shown, t = _cap(rows, 30)
    out = {"total": len(rows), "decisions": [{k: v for k, v in d.items() if k != "paths"} for d in shown],
           "pending_proposals": [{k: p[k] for k in ("proposal", "control", "requirement", "by", "path_id")}
                                 for p in pend[:CAP]],
           "note": "each decision's path_ids prove it is on record (Decision-ON->Proposal-ABOUT->Control, "
                   "Decision-ON->Proposal-TARGET->Requirement); a pending proposal's path_id re-runs as proposed, not approved"}
    if t:
        out["truncated"] = {"decisions": t}
    return out


@mcp.tool()
def stale(include_ok: bool = False) -> dict:
    """The legacy spreadsheet vs the graph: controls the tracker marks Compliant whose graph reality differs
    (no valid evidence, evidence expired, unowned, not adopted, only a proposed mapping), each with path ids.
    `no_valid_evidence` is the answer to "marked Compliant but no valid evidence today"."""
    with _reader() as conn:
        res = Q.stale(conn, None, include_ok)
    _paths(res, "stale")
    shown, t = _cap(res["stale"], 40)
    out = {"as_of": res["as_of"], "tracker_rows": res["tracker_rows"], "marked_compliant": res["marked_compliant"],
           "stale_count": res["stale_count"], "no_valid_evidence": res["no_valid_evidence"],
           "by_issue": res["by_issue"],
           "stale": [{"control": x["control"], "tracker_status": x["tracker"]["status"],
                      "tracker_last_reviewed": x["tracker"]["last_reviewed"], "tracker_owner": x["tracker"]["owner"],
                      "issues": [{"kind": i["kind"], "detail": i["detail"], "path_ids": [p["id"] for p in i["paths"]][:3]}
                                 for i in x["issues"]],
                      "tracker_path_id": x["tracker_path"]["id"]} for x in shown],
           "note": "an expired-evidence path re-runs as expired; 'NO_' paths are absence receipts (nothing owns / proves it)"}
    if t:
        out["truncated"] = {"stale": t}
    return out


@mcp.tool()
def evidence(audit: str | None = None, status: str | None = None, until: str | None = None) -> dict:
    """Evidence items with collected/expires dates and status at the store's date: `audit` (e.g. 'AUD-171') keeps
    only what that audit requests and sets the cutoff to its date; `status` is expired (already past expiry),
    expiring (valid now, gone by the cutoff), valid, or lapsed (= expired + expiring); `until` (YYYY-MM-DD)
    overrides the cutoff (default: audit date, else 30 days).  Each item has path ids (Evidence-PROVES->Control
    re-runs as expired when it is; Audit-REQUESTS->Evidence)."""
    with _reader() as conn:
        try:
            res = Q.evidence(conn, audit, status, until)
        except LookupError as exc:
            raise ValueError(str(exc.args[0]))
    _paths(res, "evidence")
    shown, t = _cap(res["evidence"], 60)
    out = {"as_of": res["as_of"], "cutoff": res["cutoff"], "audit": (res["audit"] or {}).get("id"),
           "audit_date": (res["audit"] or {}).get("date"), "status_filter": res["status_filter"],
           "counts": res["counts"], "evidence_ids": res["evidence_ids"],
           "evidence": [{"evidence": e["evidence"], "collected_at": e["collected_at"], "expires_at": e["expires_at"],
                         "status": e["status"], "days_to_expiry": e["days_to_expiry"], "controls": e["controls"],
                         "requested_by": [x["audit"] for x in e["requested_by"]],
                         "path_ids": [p["id"] for p in e["proves_paths"]][:3] + [p["id"] for p in e["request_paths"]][:3]}
                        for e in shown]}
    if t:
        out["truncated"] = {"evidence": t}
    return out


# --------------------------------------------------------------------------
# write tools: proposals only
# --------------------------------------------------------------------------


def _proposal_out(res: dict, path_nodes: tuple[list[str], list[str]] | None = None) -> dict:
    out = {k: res[k] for k in ("id", "kind", "by", "about", "target", "status", "verified", "verify_reason",
                               "reason_code", "crosswalk", "bookmark")}
    out["note"] = "a proposal is not a fact: a human must approve it (crosswalk review)"
    if path_nodes:
        out["path_id"] = C.REGISTRY.register(*path_nodes, source="propose")
    return out


def _propose(kind: str, agent: str, about: str, target: str | None, rationale: str, **extra: Any) -> dict:
    try:
        with _writer() as conn:
            return P.create_proposal(conn, kind, agent, about, target, rationale, **extra)
    except P.ProposalError as exc:
        raise ValueError(str(exc))


@mcp.tool()
def propose_mapping(control: str, requirement: str, rationale: str, agent: str = "mapper-agent") -> dict:
    """Propose that `control` satisfies `requirement`.  Verified automatically (target exists, not a duplicate,
    not previously rejected, crosswalk consistency) and stored as a pending Proposal; never a SATISFIES.
    Returns the proposal, its verification and `path_id`: the proposed path you can cite (check_claims
    will report it as proposed, not approved)."""
    res = _propose("map", agent, control, requirement, rationale)
    nodes = None
    if res["reason_code"] not in ("nonexistent_target", "withdrawn_target", "unknown_control") and res["target"]:
        nodes = ([f"Requirement:{res['target']}", f"Proposal:{res['id']}", f"Control:{control}"], ["TARGET<-", "ABOUT"])
    return _proposal_out(res, nodes)


@mcp.tool()
def propose_evidence_request(evidence: str, person: str, draft: str, agent: str = "evidence-agent") -> dict:
    """Draft a request asking `person` (id, e.g. 'P-dana-okafor'; empty = the evidence owner) to renew
    `evidence` that expires soon.  Stored as a pending Proposal with the draft text; nothing is sent."""
    return _proposal_out(_propose("evidence_request", agent, evidence, person or None,
                                  f"request to renew {evidence}", draft=draft))


@mcp.tool()
def propose_status(control: str, status: str, rationale: str, agent: str = "evidence-agent") -> dict:
    """Propose a new status for `control` (planned, partial, implemented, at_risk).  Pending Proposal only."""
    return _proposal_out(_propose("status", agent, control, status, rationale))


# --------------------------------------------------------------------------
# claim checker
# --------------------------------------------------------------------------


@mcp.tool()
def check_claims(answer: dict | str, persist: bool = True) -> dict:
    """Re-run every cited path of a draft answer ``{question, agent, claims: [{text, path_ids: [...]}]}`` and
    return, per claim, verified / partial / failed with precise reasons (expired evidence, proposed-only
    mapping, broken path, unknown id, no receipt) and a corrected answer.  With persist=true the checked
    answer is stored in the graph (Answer, Claim, Path) for the agent log."""
    try:
        with _reader() as conn:
            checked = C.check_claims(conn, answer)
            corrected = C.corrected_answer(conn, checked)
    except C.ClaimsError as exc:
        raise ValueError(str(exc))
    out: dict[str, Any] = {"as_of": checked["as_of"], "question": checked["question"], "agent": checked["agent"],
                           "counts": checked["counts"], "summary": checked["summary"],
                           "claims": [{"index": c["index"], "text": c["text"], "symbol": c["symbol"],
                                       "verdict": c["verdict"], "reasons": c["reasons"], "codes": c["codes"],
                                       "paths": [{k: p[k] for k in ("id", "status", "code", "reason", "chain")}
                                                 for p in c["paths"]]} for c in checked["claims"]],
                           "corrected": corrected}
    if persist:
        try:
            with _writer() as conn:
                out["persisted"] = C.persist(conn, checked)
        except Exception as exc:  # the check itself stands; only the audit-trail write failed
            out["persisted"] = None
            out["persist_error"] = str(exc)
    return out


def main() -> None:
    """Console entry point: serve MCP over stdio (stdout is the protocol channel; logs go to stderr)."""
    print(f"crosswalk-mcp: store {resolve_store(store_path())}", file=sys.stderr)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
