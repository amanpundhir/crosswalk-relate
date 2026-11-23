"""Human review of proposals: the only place a proposal becomes a fact.

* :func:`pending`   the review queue (pending proposals with their verification result);
* :func:`decide`    approve or reject one proposal in ONE transaction and return the bookmark;
* :func:`decisions` prior decisions with reasons.  Agents must read this before proposing.

``decide`` always writes ``(:Decision {id, outcome, reason, by, at, forced})-[:ON]->(:Proposal)`` and
``(:Change {id, at, actor, action, detail})-[:CHANGED]->(:Proposal)``.  An approved ``map`` also creates
``(:Control)-[:SATISFIES {approved_by, approved_at, via_proposal}]->(:Requirement)`` (the only place
SATISFIES is written after the build); an approved ``status`` sets ``Control.status``; an approved
``evidence_request`` just records that a human sent it.  Dates default to ``Meta.as_of``.
"""

from __future__ import annotations

import relate

from crosswalk.paths import make_path
from crosswalk.proposals import (_rollback, as_of_date, get_proposal, is_locked, is_retryable, list_proposals,
                                 next_id, normalise_id)
from crosswalk.verify import verify

_OUTCOMES = {"approved": "approved", "approve": "approved", "rejected": "rejected", "reject": "rejected"}


class ReviewError(RuntimeError):
    """The decision could not be recorded; the message says why and what to do."""


def _edges(conn: relate.Connection, where: str = "") -> dict[str, dict]:
    """``{proposal id: {about: 'Label:id' | None, target: 'Label:id' | None}}`` from the edges that really exist."""
    rows = conn.execute(
        "MATCH (p:Proposal) " + where + "OPTIONAL MATCH (p)-[:ABOUT]->(x) OPTIONAL MATCH (p)-[:TARGET]->(t) "
        "RETURN p.id AS id, labels(x)[0] AS xl, x.id AS xid, labels(t)[0] AS tl, t.id AS tid").fetchall()
    return {r["id"]: {"about": f"{r['xl']}:{r['xid']}" if r["xid"] else None,
                      "target": f"{r['tl']}:{r['tid']}" if r["tid"] else None} for r in rows}


def proposal_paths(proposal: str, about: str | None, target: str | None, decision: str | None = None) -> list[dict]:
    """Citable receipts for a proposal (and its decision): ``Proposal -ABOUT-> Control|Evidence``,
    ``Proposal -TARGET-> Requirement|Person``, for a mapping also ``Requirement <-TARGET- Proposal -ABOUT-> Control``
    (the proposed path), and with ``decision`` ``Decision -ON-> Proposal -ABOUT-> ...`` /
    ``Decision -ON-> Proposal -TARGET-> ...``.  ``about`` / ``target`` are ``Label:id`` references.  A pending
    proposal re-runs as "proposed, not approved"; a decision path re-runs valid whenever the decision is on record."""
    p = f"Proposal:{proposal}"
    out = []
    if decision:
        if about:
            out.append(make_path([f"Decision:{decision}", p, about], ["ON", "ABOUT"]))
        if target:
            out.append(make_path([f"Decision:{decision}", p, target], ["ON", "TARGET"]))
    else:
        if about:
            out.append(make_path([p, about], ["ABOUT"]))
        if target:
            out.append(make_path([p, target], ["TARGET"]))
        if about and target and about.startswith("Control:") and target.startswith("Requirement:"):
            out.append(make_path([target, p, about], ["TARGET<-", "ABOUT"]))
    return out


def pending(conn: relate.Connection) -> list[dict]:
    """Pending proposals, oldest first.  ``verified`` is None for a proposal nobody has verified yet.
    Each row carries ``paths`` / ``path_ids`` (see :func:`proposal_paths`)."""
    rows = list_proposals(conn, "pending")
    edges = _edges(conn, "WHERE p.status = 'pending' ")
    for r in rows:
        e = edges.get(r["id"], {})
        r["paths"] = proposal_paths(r["id"], e.get("about"), e.get("target"))
        r["path_ids"] = [p["id"] for p in r["paths"]]
    return rows


# --------------------------------------------------------------------------
# decide
# --------------------------------------------------------------------------


def _decide_once(conn, pid, outcome, by, reason, force, at) -> str:
    conn.autocommit = False
    p = get_proposal(conn, pid)
    if p is None:
        raise ReviewError(f"no proposal {pid}")
    if p["status"] != "pending":
        raise ReviewError(f"{pid} is already {p['status']}; only pending proposals can be decided")
    when = as_of_date(conn, at)
    verified, vreason = p["verified"], p["verify_reason"]
    if verified is None:  # created before the verifier existed (the seeded pack): verify it now
        v = verify(conn, {"id": pid, "kind": p["kind"], "about": p["about"], "target": p["target"],
                          "by": p["by"], "rationale": p["rationale"]}, as_of=when)
        verified, vreason = v["verified"], v["reason"]
        conn.execute("MATCH (p:Proposal {id: $id}) SET p.verified = $v, p.verify_reason = $r",
                     {"id": pid, "v": verified, "r": vreason})
    approving = outcome == "approved"
    forced = approving and not verified
    if forced and not force:
        raise ReviewError(f"{pid} failed verification ({vreason}); refusing to approve it. "
                          f"Reject it, or approve with force=True / --force (recorded in the decision).")

    applied = ""
    if approving and p["kind"] == "map":
        if not conn.execute("MATCH (:Control {id: $c}) RETURN 1 AS ok", {"c": p["about"]}).fetchall() or \
           not conn.execute("MATCH (:Requirement {id: $r}) RETURN 1 AS ok", {"r": p["target"]}).fetchall():
            raise ReviewError(f"{pid}: control {p['about']} or requirement {p['target']} does not exist, "
                              f"so it cannot be approved")
        have = conn.execute("MATCH (:Control {id: $c})-[s:SATISFIES]->(:Requirement {id: $r}) "
                            "RETURN s.approved_by AS by", {"c": p["about"], "r": p["target"]}).fetchall()
        if have:
            raise ReviewError(f"{pid}: {p['about']} already satisfies {p['target']} (approved by {have[0]['by']}); "
                              f"reject this proposal as a duplicate instead")
        conn.execute("MATCH (c:Control {id: $c}) MATCH (r:Requirement {id: $r}) "
                     "CREATE (c)-[:SATISFIES {approved_by: $by, approved_at: date($at), via_proposal: $pid}]->(r)",
                     {"c": p["about"], "r": p["target"], "by": by, "at": when, "pid": pid})
        applied = f"created SATISFIES {p['about']} -> {p['target']}"
    elif approving and p["kind"] == "status":
        if not conn.execute("MATCH (c:Control {id: $c}) SET c.status = $s RETURN 1 AS ok",
                            {"c": p["about"], "s": p["new_status"]}).fetchall():
            raise ReviewError(f"{pid}: control {p['about']} does not exist")
        applied = f"set {p['about']} status {p.get('old_status')} -> {p['new_status']}"
    elif approving:
        applied = f"evidence request for {p['about']} to {p['target']} approved for sending"

    did = next_id(conn, "Decision", "D")
    cid = next_id(conn, "Change", "CH")
    conn.execute("MATCH (p:Proposal {id: $id}) SET p.status = $o", {"id": pid, "o": outcome})
    conn.execute("MATCH (p:Proposal {id: $p}) "
                 "CREATE (d:Decision {id: $d, outcome: $o, reason: $r, by: $by, at: date($at), forced: $f}) "
                 "CREATE (d)-[:ON]->(p)",
                 {"p": pid, "d": did, "o": outcome, "r": reason, "by": by, "at": when, "f": forced})
    verb = "approve" if approving else "reject"
    detail = (f"{applied or 'no change to facts'} via {pid} ({did}); reason: {reason}"
              + (f"; FORCED past failed verification: {vreason}" if forced else ""))
    conn.execute("MATCH (p:Proposal {id: $p}) "
                 "CREATE (c:Change {id: $c, at: date($at), actor: $by, action: $a, detail: $d}) "
                 "CREATE (c)-[:CHANGED]->(p)",
                 {"p": pid, "c": cid, "at": when, "by": by, "a": f"{verb}_{p['kind']}", "d": detail})
    if applied and p["kind"] in ("map", "status"):
        conn.execute("MATCH (c:Change {id: $c}) MATCH (x:Control {id: $x}) CREATE (c)-[:CHANGED]->(x)",
                     {"c": cid, "x": p["about"]})
    return conn.commit()


def decide(conn: relate.Connection, proposal_id: str, outcome: str, by: str, reason: str,
           force: bool = False, at: str | None = None, retries: int = 1) -> str:
    """Approve or reject a pending proposal in one transaction; returns the commit bookmark.

    ``outcome`` is ``approved`` or ``rejected`` (``approve``/``reject`` also work).  Approving a
    proposal that failed (or never had) verification is refused unless ``force=True``; the forced
    approval is recorded on the Decision (``forced: true``) and in the Change detail.  A retryable
    write-write conflict is retried ``retries`` times (default once), then reported as a
    :class:`ReviewError`.  ``at`` defaults to ``Meta.as_of``.
    """
    out = _OUTCOMES.get(str(outcome).strip().lower())
    if out is None:
        raise ReviewError(f"outcome must be approved or rejected, not {outcome!r}")
    if not str(by or "").strip():
        raise ReviewError("a decision needs the reviewer's id (by)")
    if not str(reason or "").strip():
        raise ReviewError("a decision needs a reason (it is stored, and agents read it before proposing)")
    pid = normalise_id(proposal_id, "PR")
    attempt = 0
    while True:
        attempt += 1
        try:
            return _decide_once(conn, pid, out, by, reason.strip(), force, at)
        except ReviewError:
            _rollback(conn)
            raise
        except Exception as exc:
            _rollback(conn)
            if is_retryable(exc):
                if attempt <= retries:
                    continue
                raise ReviewError(f"another writer changed the same data at the same time (write-write conflict) "
                                  f"and the retry failed too; nothing was recorded for {pid}, run the decision "
                                  f"again: {exc}") from exc
            if is_locked(exc):
                raise ReviewError("another writer has the store open; close it and run the decision again") from exc
            raise


# --------------------------------------------------------------------------
# decisions (memory)
# --------------------------------------------------------------------------


def decisions(conn: relate.Connection, about: str | None = None) -> list[dict]:
    """Prior decisions with their reasons, oldest first.

    With ``about`` (a control, requirement, evidence or person id) only decisions touching it are
    returned: ``relation`` is ``direct`` (the proposal was about / aimed at ``about``) or ``sibling``
    (a different control of the same policy as the control ``about``; the evidence behind the
    verifier's sibling-rejection rule).  Each row: id, outcome, reason, by, at, proposal, kind, about,
    target, relation, forced, and the receipts ``paths`` / ``path_ids``: ``Decision -ON-> Proposal -ABOUT->
    Control`` and ``Decision -ON-> Proposal -TARGET-> Requirement`` (see :func:`proposal_paths`).
    """
    rows = [dict(r) for r in conn.execute(
        "MATCH (d:Decision)-[:ON]->(p:Proposal) OPTIONAL MATCH (p)-[:ABOUT]->(x) OPTIONAL MATCH (p)-[:TARGET]->(t) "
        "RETURN labels(x)[0] AS about_label, labels(t)[0] AS target_label, d.id AS id, d.outcome AS outcome, d.reason AS reason, d.by AS by, toString(d.at) AS at, "
        "coalesce(d.forced, false) AS forced, p.id AS proposal, p.kind AS kind, x.id AS about, t.id AS target, "
        "x.policy AS policy ORDER BY d.id").fetchall()]
    policy = None
    if about:
        got = conn.execute("MATCH (c:Control {id: $c}) RETURN c.policy AS p", {"c": about}).fetchall()
        policy = got[0]["p"] if got else None
    out = []
    for r in rows:
        xl, tl = r.pop("about_label", None), r.pop("target_label", None)
        r["paths"] = proposal_paths(r["proposal"], f"{xl}:{r['about']}" if r["about"] else None,
                                    f"{tl}:{r['target']}" if r["target"] else None, decision=r["id"])
        r["path_ids"] = [p["id"] for p in r["paths"]]
        r_policy = r.pop("policy", None)
        if about is None:
            r["relation"] = "direct"
        elif about in (r["about"], r["target"]):
            r["relation"] = "direct"
        elif policy and r_policy == policy:
            r["relation"] = "sibling"
        else:
            continue
        out.append(r)
    return out
