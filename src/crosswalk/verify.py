"""The proposal verifier: every proposal is checked automatically before a human sees it.

``verify(conn, proposal)`` is read-only.  It returns ``{"verified", "reason", "reason_code",
"reasons", "checks", "crosswalk"}``:

* ``verified``     True only if every blocking check passed;
* ``reason``       ``"verified: ..."`` or ``"<code>: <human wording>"`` of the FIRST failing check;
* ``reason_code``  that first failing code (``None`` when verified), ``reasons`` all failing codes;
* ``checks``       ``[{"check", "ok", "detail"[, "code", "info"]}]``, one entry per check that ran;
* ``crosswalk``    ``"agrees"``, ``"no_link"`` or ``"n/a"`` (informational, never a failure).

The failure codes are stable (``eval/bad_proposals.yaml`` pins them): ``contradictory_status``,
``nonexistent_target``, ``withdrawn_target``, ``wrong_framework``, ``unknown_control``,
``control_not_adopted``, ``duplicate``, ``previously_rejected``, ``unknown_evidence``,
``unknown_person``, ``evidence_not_expiring``, ``invalid_status``, ``no_change``,
``implemented_without_evidence``.

A proposal is a plain dict.  Canonical keys: ``kind`` (``map`` | ``status`` | ``evidence_request`` |
``ownership``), ``about``, ``target``, ``by``, ``rationale``; optional ``id`` (a stored proposal is
never its own duplicate), ``status`` (the claimed status; agents may only claim ``pending``),
``target_framework``, ``decided_by``/``decision``.  :func:`normalise_proposal` also accepts the
``eval/bad_proposals.yaml`` shape (``type``/``control``/``requirement``/``evidence``/``owner``).

======================  =========================  ==============================
kind                    about                      target
======================  =========================  ==============================
``map``                 Control id                 Requirement id
``status``              Control id                 new status (planned, partial, implemented, at_risk)
``evidence_request``    Evidence id                Person id (default: the evidence owner)
``ownership``           Control id                 Person id (verify only)
======================  =========================  ==============================
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any

import relate

from crosswalk.build import NIST_RAW_DIR
from crosswalk.coverage import read_as_of

EXPIRY_WINDOW_DAYS = 60
VALID_STATUSES = ("planned", "partial", "implemented", "at_risk")
KINDS = ("map", "status", "evidence_request", "ownership")
_KIND_ALIASES = {"mapping": "map", "map": "map", "status": "status", "status_change": "status",
                 "evidence_request": "evidence_request", "evidence": "evidence_request",
                 "ownership": "ownership", "owner": "ownership"}


# --------------------------------------------------------------------------
# Normalising input
# --------------------------------------------------------------------------


def normalise_status(value: Any) -> str | None:
    return None if value is None else str(value).strip().lower().replace(" ", "_").replace("-", "_")


def normalise_proposal(p: dict) -> dict:
    """Canonical proposal dict (``kind``/``about``/``target``) from either input shape."""
    d = dict(p)
    kind = _KIND_ALIASES.get(str(d.get("kind") or d.get("type") or "").lower())
    if kind is None:
        raise ValueError(f"unknown proposal kind {d.get('kind') or d.get('type')!r}; expected one of {KINDS}")
    d["kind"] = kind
    if kind in ("map", "status", "ownership"):
        d.setdefault("about", d.get("control"))
        d.setdefault("target", {"map": d.get("requirement"), "status": d.get("new_status"),
                                "ownership": d.get("owner")}[kind])
    else:
        d.setdefault("about", d.get("evidence"))
        d.setdefault("target", d.get("person") or d.get("owner"))
    if kind == "status":
        d["target"] = normalise_status(d.get("target"))
    return d


@lru_cache(maxsize=1)
def withdrawn_ids() -> frozenset[str]:
    """Requirement ids that NIST withdrew (they are not loaded into the graph, so they need the catalogs)."""
    try:
        from crosswalk.sources import nist

        loaded = nist._load_all(NIST_RAW_DIR)
        return frozenset().union(*(w for _reqs, _fams, w in loaded.values()))
    except Exception:  # catalogs not on disk: withdrawn ids then read as nonexistent
        return frozenset()


def resolve_target(conn: relate.Connection, target: str | None) -> str | None:
    """A requirement id from a full or short id when it exists, else the input unchanged."""
    if not target:
        return target
    from crosswalk.queries import resolve_requirement

    try:
        return resolve_requirement(conn, str(target))
    except LookupError:
        return str(target)


# --------------------------------------------------------------------------
# Graph look-ups (all read-only)
# --------------------------------------------------------------------------


def _one(conn: relate.Connection, cypher: str, **params: Any) -> dict | None:
    rows = conn.execute(cypher, params).fetchall()
    return dict(rows[0]) if rows else None


def _control(conn, cid):
    return _one(conn, "MATCH (c:Control {id: $id}) RETURN c.id AS id, c.adopted AS adopted, c.status AS status, "
                      "c.policy AS policy, c.title AS title", id=cid)


def _requirement(conn, rid):
    return _one(conn, "MATCH (r:Requirement {id: $id}) RETURN r.id AS id, r.framework AS framework", id=rid)


def _person(conn, pid):
    return _one(conn, "MATCH (p:Person {id: $id}) RETURN p.id AS id, p.name AS name", id=pid)


def _evidence(conn, eid):
    return _one(conn, "MATCH (e:Evidence {id: $id}) RETURN e.id AS id, toString(e.expires_at) AS expires_at, "
                      "e.title AS title", id=eid)


def _chk(check: str, ok: bool, detail: str, code: str | None = None, info: bool = False) -> dict:
    out = {"check": check, "ok": bool(ok), "detail": detail}
    if not ok and code:
        out["code"] = code
    if info:
        out["info"] = True
    return out


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


def _check_status_claim(p: dict) -> dict:
    claimed = p.get("status")
    if claimed in (None, "", "pending"):
        return _chk("agent_proposes_only", True, "status is pending: only a human decision can approve")
    missing = [k for k in ("decided_by", "decision") if not p.get(k)]
    why = ("no approver or decision is recorded" if missing
           else "agents cannot create decided proposals")
    return _chk("agent_proposes_only", False,
                f"proposal claims status {claimed!r} but {why}; agents can only propose "
                f"(only a human `review` approve or reject changes a status)", "contradictory_status")


def _check_control(conn, cid, need_adopted: bool) -> tuple[list[dict], dict | None]:
    c = _control(conn, cid) if cid else None
    if c is None:
        return [_chk("control_exists", False, f"control {cid!r} does not exist", "unknown_control")], None
    out = [_chk("control_exists", True, f"{cid} exists ({c['title']})" if c.get("title") else f"{cid} exists")]
    if need_adopted:
        ok = bool(c.get("adopted"))
        out.append(_chk("control_adopted", ok,
                        f"{cid} is adopted" if ok else f"{cid} is in the library but not adopted by the company",
                        "control_not_adopted"))
    return out, c


def _check_requirement_target(conn, tid, declared_framework) -> tuple[list[dict], dict | None]:
    r = _requirement(conn, tid) if tid else None
    if r is None:
        if tid in withdrawn_ids():
            return [_chk("target_exists", False,
                         f"{tid} is withdrawn by NIST (incorporated elsewhere) and cannot be a mapping target",
                         "withdrawn_target")], None
        return [_chk("target_exists", False, f"requirement {tid!r} does not exist", "nonexistent_target")], None
    out = [_chk("target_exists", True, f"{tid} exists in {r['framework']}")]
    if declared_framework:
        ok = str(declared_framework) == r["framework"]
        out.append(_chk("framework_matches", ok,
                        f"{tid} is in {r['framework']}" if ok else
                        f"proposal declares target_framework {declared_framework} but {tid} belongs to {r['framework']}",
                        "wrong_framework"))
    return out, r


def _check_duplicate_map(conn, cid, tid, own_id) -> dict:
    row = _one(conn, "MATCH (c:Control {id: $c})-[s:SATISFIES]->(r:Requirement {id: $t}) "
                     "RETURN s.approved_by AS by, toString(s.approved_at) AS at", c=cid, t=tid)
    if row:
        return _chk("not_duplicate", False, f"already satisfied: {cid} -> {tid} approved by {row['by']} on {row['at']}",
                    "duplicate")
    row = _one(conn, "MATCH (p:Proposal {status: 'pending'})-[:ABOUT]->(:Control {id: $c}) "
                     "MATCH (p)-[:TARGET]->(:Requirement {id: $t}) "
                     "WHERE p.kind = 'map' AND p.id <> $own AND coalesce(p.verified, true) = true "
                     "RETURN p.id AS id ORDER BY p.id LIMIT 1", c=cid, t=tid, own=own_id or "")
    if row:
        return _chk("not_duplicate", False, f"an identical proposal is already pending: {row['id']}", "duplicate")
    return _chk("not_duplicate", True, f"{cid} -> {tid} is not yet approved or pending")


def _check_not_rejected(conn, cid, tid, policy, own_id) -> dict:
    rows = conn.execute(
        "MATCH (d:Decision {outcome: 'rejected'})-[:ON]->(p:Proposal)-[:ABOUT]->(c:Control) "
        "MATCH (p)-[:TARGET]->(:Requirement {id: $t}) "
        "WHERE p.id <> $own AND (c.id = $c OR ($pol IS NOT NULL AND c.policy = $pol)) "
        "RETURN d.id AS decision, d.by AS by, toString(d.at) AS at, d.reason AS reason, c.id AS control, p.id AS proposal "
        "ORDER BY (c.id = $c) DESC, d.id", {"t": tid, "c": cid, "pol": policy, "own": own_id or ""}).fetchall()
    if not rows:
        return _chk("not_previously_rejected", True, "no earlier rejection of this mapping or of a sibling control's")
    r = rows[0]
    kind = "this exact mapping" if r["control"] == cid else f"the same target from {r['control']} (same policy)"
    return _chk("not_previously_rejected", False,
                f"rejected by {r['by']} on {r['at']} ({r['decision']}, {kind}): \"{r['reason']}\"",
                "previously_rejected")


def _check_crosswalk(conn, cid, tid) -> tuple[dict, str]:
    own = conn.execute(
        "MATCH (:Control {id: $c})-[:SATISFIES]->(r:Requirement)-[:EQUIVALENT_TO]-(t:Requirement {id: $t}) "
        "RETURN DISTINCT r.id AS id ORDER BY id", {"c": cid, "t": tid}).fetchall()
    if own:
        ids = ", ".join(r["id"] for r in own)
        return _chk("crosswalk_consistency", True, f"agrees with NIST: {cid} already satisfies {ids}, "
                    f"which the NIST crosswalk links to {tid}", info=True), "agrees"
    other = conn.execute(
        "MATCH (t:Requirement {id: $t})-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c:Control) "
        "RETURN DISTINCT n.id AS req, c.id AS control ORDER BY req, control LIMIT 3", {"t": tid}).fetchall()
    if other:
        txt = ", ".join(f"{r['req']} (approved for {r['control']})" for r in other)
        return _chk("crosswalk_consistency", True,
                    f"agrees with NIST: {tid} is linked to approved requirement(s) {txt}", info=True), "agrees"
    return _chk("crosswalk_consistency", True,
                f"no NIST link between {tid} and anything this control or the company has approved: "
                f"flag for careful review", info=True), "no_link"


def _valid_evidence(conn, cid, as_of) -> list[str]:
    return [r["id"] for r in conn.execute(
        "MATCH (e:Evidence)-[:PROVES]->(:Control {id: $c}) WHERE e.expires_at > date($d) "
        "RETURN e.id AS id ORDER BY id", {"c": cid, "d": as_of}).fetchall()]


def _verify_map(conn, p: dict) -> tuple[list[dict], str]:
    cid, tid, own = p.get("about"), p.get("target"), p.get("id")
    checks: list[dict] = []
    tchecks, req = _check_requirement_target(conn, tid, p.get("target_framework"))
    cchecks, ctrl = _check_control(conn, cid, need_adopted=True)
    adopted = [c for c in cchecks if c["check"] == "control_adopted"]
    checks += tchecks + [c for c in cchecks if c["check"] != "control_adopted"]
    xw = "n/a"
    if req and ctrl:  # an earlier rejection is more useful to report than "not adopted", so adoption comes after
        checks.append(_check_duplicate_map(conn, cid, tid, own))
        checks.append(_check_not_rejected(conn, cid, tid, ctrl.get("policy"), own))
        checks += adopted
        c, xw = _check_crosswalk(conn, cid, tid)
        checks.append(c)
    else:
        checks += adopted
    return checks, xw


def _verify_status(conn, p: dict, as_of: str) -> list[dict]:
    cid, new = p.get("about"), p.get("target")
    checks, ctrl = _check_control(conn, cid, need_adopted=False)
    ok = new in VALID_STATUSES
    checks.append(_chk("status_valid", ok, f"{new!r} is a valid status" if ok else
                       f"{new!r} is not a valid status (expected one of {', '.join(VALID_STATUSES)})",
                       "invalid_status"))
    if ctrl is None or not ok:
        return checks
    old = ctrl.get("status")
    if old == new:
        checks.append(_chk("status_transition", False, f"{cid} already has status {new!r}", "no_change"))
        return checks
    valid = _valid_evidence(conn, cid, as_of)
    if new == "implemented" and not valid:
        checks.append(_chk("status_transition", False,
                           f"{cid} cannot be 'implemented': no evidence proving it is valid at {as_of}",
                           "implemented_without_evidence"))
    elif new == "at_risk" and valid:
        checks.append(_chk("status_transition", True,
                           f"{old} -> at_risk although {', '.join(valid)} is still valid at {as_of}: "
                           f"flag for careful review", info=True))
    else:
        why = (f"valid evidence {', '.join(valid)}" if valid else f"no valid evidence at {as_of}")
        checks.append(_chk("status_transition", True, f"{old} -> {new} is consistent with the evidence ({why})"))
    pend = _one(conn, "MATCH (p:Proposal {kind: 'status', status: 'pending'})-[:ABOUT]->(:Control {id: $c}) "
                      "WHERE p.new_status = $s AND p.id <> $own AND coalesce(p.verified, true) = true "
                      "RETURN p.id AS id LIMIT 1", c=cid, s=new, own=p.get("id") or "")
    if pend:
        checks.append(_chk("not_duplicate", False, f"an identical proposal is already pending: {pend['id']}", "duplicate"))
    return checks


def _verify_evidence_request(conn, p: dict, as_of: str) -> list[dict]:
    eid, pid = p.get("about"), p.get("target")
    checks: list[dict] = []
    ev = _evidence(conn, eid) if eid else None
    if ev is None:
        return [_chk("evidence_exists", False, f"evidence {eid!r} does not exist", "unknown_evidence")]
    checks.append(_chk("evidence_exists", True, f"{eid} exists"))
    if not pid:
        owner = _one(conn, "MATCH (p:Person)-[:OWNS]->(:Evidence {id: $e}) RETURN p.id AS id LIMIT 1", e=eid)
        pid = owner["id"] if owner else None
        if pid is None:
            checks.append(_chk("person_exists", False, f"no person given and {eid} has no owner", "unknown_person"))
    if pid:
        ok = _person(conn, pid) is not None
        checks.append(_chk("person_exists", ok, f"{pid} is a known person" if ok else
                           f"person {pid!r} is not in the people list", "unknown_person"))
    days = (dt.date.fromisoformat(ev["expires_at"]) - dt.date.fromisoformat(as_of)).days
    ok = days <= EXPIRY_WINDOW_DAYS
    checks.append(_chk("evidence_expiring", ok,
                       f"{eid} expires {ev['expires_at']} ({days} days after {as_of})" if ok else
                       f"{eid} is valid until {ev['expires_at']} ({days} days after {as_of}), outside the "
                       f"{EXPIRY_WINDOW_DAYS}-day window, so no request is needed", "evidence_not_expiring"))
    pend = _one(conn, "MATCH (p:Proposal {kind: 'evidence_request', status: 'pending'})-[:ABOUT]->(:Evidence {id: $e}) "
                      "WHERE p.id <> $own AND coalesce(p.verified, true) = true RETURN p.id AS id LIMIT 1",
                e=eid, own=p.get("id") or "")
    if pend:
        checks.append(_chk("not_duplicate", False, f"a request for {eid} is already pending: {pend['id']}", "duplicate"))
    return checks


def _verify_ownership(conn, p: dict) -> list[dict]:
    checks, _ctrl = _check_control(conn, p.get("about"), need_adopted=True)
    pid = p.get("target")
    ok = bool(pid) and _person(conn, pid) is not None
    checks.append(_chk("person_exists", ok, f"{pid} is a known person" if ok else
                       f"person {pid!r} is not in the people list (not an employee, or departed)", "unknown_person"))
    return checks


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def verify(conn: relate.Connection, proposal: dict, as_of: str | None = None) -> dict:
    """Run every check for ``proposal`` (see the module docstring).  Reads only."""
    p = normalise_proposal(proposal)
    at = as_of or read_as_of(conn)
    checks = [_check_status_claim(p)]
    xw = "n/a"
    if p["kind"] == "map":
        c, xw = _verify_map(conn, p)
        checks += c
    elif p["kind"] == "status":
        checks += _verify_status(conn, p, at)
    elif p["kind"] == "evidence_request":
        checks += _verify_evidence_request(conn, p, at)
    else:
        checks += _verify_ownership(conn, p)
    failed = [c for c in checks if not c["ok"]]
    # Order of `checks` is the order the checks run in: the first failure is the reported reason.
    if failed:
        first = failed[0]
        reason = f"{first.get('code', first['check'])}: {first['detail']}"
        code = first.get("code", first["check"])
    else:
        notes = [c["detail"] for c in checks if c.get("info")]
        reason = "verified" + (": " + "; ".join(notes) if notes else "")
        code = None
    return {"verified": not failed, "reason": reason, "reason_code": code,
            "reasons": [c.get("code", c["check"]) for c in failed], "checks": checks, "crosswalk": xw}
