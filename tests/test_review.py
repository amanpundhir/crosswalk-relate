"""Tests for crosswalk.verify, proposals, review and the concurrency demo.

Every test works on a throw-away store under tmp (built once per session, copied per test); nothing
here touches data/crosswalk.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import relate
import yaml

from crosswalk import build as B
from crosswalk import demo_concurrency as demo
from crosswalk import proposals as P
from crosswalk import queries as Q
from crosswalk import review as R
from crosswalk.verify import verify

REPO = Path(__file__).resolve().parents[1]
BAD = yaml.safe_load((REPO / "eval" / "bad_proposals.yaml").read_text(encoding="utf-8"))
MAYA = "P-maya-chen"


@pytest.fixture(scope="session")
def base_store(tmp_path_factory):
    store = tmp_path_factory.mktemp("review-base") / "crosswalk"
    B.build(store, export=False)
    return store


@pytest.fixture(scope="module")
def pristine(base_store):
    """Read-only handle on the freshly built store (for verifier-only tests)."""
    conn = relate.connect(str(base_store), read_only=True)
    yield conn
    conn.close()


@pytest.fixture()
def store(base_store, tmp_path):
    dest = tmp_path / "crosswalk"
    shutil.copytree(base_store, dest)
    return dest


@pytest.fixture()
def conn(store):
    c = P.open_writer(store)
    yield c
    c.close()


def _one(conn, cypher, **params):
    return [dict(r) for r in conn.execute(cypher, params).fetchall()]


def _clean_map_candidate(conn) -> tuple[str, str]:
    """(control with valid evidence, 800-171 gap requirement) that the verifier accepts."""
    as_of = "2026-12-02"
    controls = [r["id"] for r in _one(
        conn, "MATCH (c:Control {adopted: true})<-[:PROVES]-(e:Evidence) WHERE e.expires_at > date($d) "
              "RETURN DISTINCT c.id AS id ORDER BY id", d=as_of)]
    gaps = [r["id"] for r in Q.coverage(conn, "800-171")["requirements"] if r["status"] == "gap"]
    for req in gaps:
        for ctrl in controls:
            if verify(conn, {"kind": "map", "about": ctrl, "target": req, "by": "mapper-agent"})["verified"]:
                return ctrl, req
    pytest.fail("no verifiable control/requirement pair in the pack")


def _covered_ids(conn, fw="800-171") -> set[str]:
    return {r["id"] for r in Q.coverage(conn, fw)["requirements"] if r["status"] == "covered"}


# --------------------------------------------------------------------------
# the 8 bad proposals
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", BAD, ids=[b["id"] for b in BAD])
def test_bad_proposal_fails_with_expected_reason(pristine, bad):
    res = verify(pristine, bad["proposal"])
    assert res["verified"] is False
    assert res["reason_code"] == bad["expected_reason"]
    assert res["reason"].startswith(bad["expected_reason"])
    assert bad["expected_reason"] in res["reasons"]
    failing = [c for c in res["checks"] if not c["ok"]]
    assert failing and all({"check", "ok", "detail"} <= set(c) for c in res["checks"])


def test_bad_proposals_are_stored_unverified_and_never_become_facts(conn):
    before = _one(conn, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n")[0]["n"]
    p = P.create_proposal(conn, "map", "mapper-agent", "CTRL-AP-12", "800-53:CP-4", "again")  # BP-01
    assert p["verified"] is False and p["reason_code"] == "duplicate"
    row = _one(conn, "MATCH (p:Proposal {id: $id}) RETURN p.status AS s, p.verified AS v, p.verify_reason AS r, "
                     "p.checks AS c", id=p["id"])[0]
    assert (row["s"], row["v"]) == ("pending", False) and row["r"].startswith("duplicate")
    assert any(not c["ok"] for c in json.loads(row["c"]))
    assert _one(conn, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n")[0]["n"] == before


def test_status_claim_cannot_be_stored_as_approved(conn):  # BP-08 through create_proposal
    p = P.create_proposal(conn, "map", "mapper-agent", "CTRL-PWP-4", "800-171:03.05.03", "pending review",
                          status="approved")
    assert p["reason_code"] == "contradictory_status"
    assert _one(conn, "MATCH (p:Proposal {id: $id}) RETURN p.status AS s", id=p["id"])[0]["s"] == "pending"


# --------------------------------------------------------------------------
# S4: the earlier rejection
# --------------------------------------------------------------------------


def test_s4_exact_rejection_reports_who_when_and_why(pristine):
    res = verify(pristine, {"kind": "map", "about": "CTRL-AOTP-11", "target": "800-53:AC-17", "by": "mapper-agent"})
    assert res["reason_code"] == "previously_rejected"
    for needle in ("P-maya-chen", "2026-11-25", "D-001", "AC-17 is remote access"):
        assert needle in res["reason"]


def test_s4_sibling_control_of_the_same_policy_is_also_caught(pristine):
    # CTRL-AOTP-4 is the "new control" of the S4 demo; AOTP-11 (same policy) was rejected for AC-17.
    res = verify(pristine, {"kind": "map", "about": "CTRL-AOTP-4", "target": "800-53:AC-17", "by": "mapper-agent"})
    assert "previously_rejected" in res["reasons"]
    rej = next(c for c in res["checks"] if c["check"] == "not_previously_rejected")
    assert "CTRL-AOTP-11" in rej["detail"] and "same policy" in rej["detail"] and "P-maya-chen" in rej["detail"]


def test_decisions_helper_shows_memory(pristine):
    direct = R.decisions(pristine, "CTRL-AOTP-11")
    assert [d["id"] for d in direct if d["relation"] == "direct"] == ["D-001"]
    d1 = direct[0]
    assert (d1["outcome"], d1["by"], d1["at"]) == ("rejected", MAYA, "2026-11-25")
    assert "remote access" in d1["reason"]
    sib = [d for d in R.decisions(pristine, "CTRL-AOTP-4") if d["id"] == "D-001"]
    assert sib and sib[0]["relation"] == "sibling"
    assert {d["id"] for d in R.decisions(pristine)} == {"D-001", "D-002", "D-003", "D-004"}
    assert {d["id"] for d in R.decisions(pristine, "800-53:SC-8")} == {"D-002"}


# --------------------------------------------------------------------------
# approve / reject
# --------------------------------------------------------------------------


def test_approve_creates_satisfies_decision_change_and_moves_coverage(conn):
    ctrl, req = _clean_map_candidate(conn)
    before = _covered_ids(conn)
    assert req not in before
    prop = P.create_proposal(conn, "map", "mapper-agent", ctrl, req, "test mapping")
    assert prop["id"] == "PR-009" and prop["verified"] is True
    assert [p["id"] for p in R.pending(conn)][-1] == "PR-009"
    assert _covered_ids(conn) == before  # a proposal is not a fact
    assert _one(conn, "MATCH (:Control {id: $c})-[s:SATISFIES]->(:Requirement {id: $r}) RETURN s", c=ctrl, r=req) == []

    bookmark = R.decide(conn, "PR-009", "approved", MAYA, "fits the requirement")
    assert bookmark.startswith("relate:")

    sat = _one(conn, "MATCH (:Control {id: $c})-[s:SATISFIES]->(:Requirement {id: $r}) "
                     "RETURN s.approved_by AS by, toString(s.approved_at) AS at, s.via_proposal AS via", c=ctrl, r=req)
    assert sat == [{"by": MAYA, "at": "2026-12-02", "via": "PR-009"}]
    assert _one(conn, "MATCH (p:Proposal {id: 'PR-009'}) RETURN p.status AS s")[0]["s"] == "approved"
    dec = _one(conn, "MATCH (d:Decision)-[:ON]->(:Proposal {id: 'PR-009'}) RETURN d.outcome AS o, d.reason AS r, "
                     "d.by AS by, toString(d.at) AS at, d.forced AS f")
    assert dec == [{"o": "approved", "r": "fits the requirement", "by": MAYA, "at": "2026-12-02", "f": False}]
    chg = _one(conn, "MATCH (c:Change)-[:CHANGED]->(:Proposal {id: 'PR-009'}) RETURN c.actor AS a, c.action AS x, "
                     "c.detail AS d, toString(c.at) AS at")
    assert len(chg) == 1 and chg[0]["a"] == MAYA and chg[0]["x"] == "approve_map" and ctrl in chg[0]["d"]
    after = _covered_ids(conn)
    assert after - before == {req} and before <= after


def test_reject_stores_decision_and_changes_no_fact(conn):
    ctrl, req = _clean_map_candidate(conn)
    before = _covered_ids(conn)
    P.create_proposal(conn, "map", "mapper-agent", ctrl, req, "test mapping")
    R.decide(conn, "PR-9", "rejected", MAYA, "not what the requirement asks")  # short id works
    assert _one(conn, "MATCH (p:Proposal {id: 'PR-009'}) RETURN p.status AS s")[0]["s"] == "rejected"
    assert _one(conn, "MATCH (:Control {id: $c})-[s:SATISFIES]->(:Requirement {id: $r}) RETURN s", c=ctrl, r=req) == []
    dec = _one(conn, "MATCH (d:Decision)-[:ON]->(:Proposal {id: 'PR-009'}) RETURN d.outcome AS o, d.reason AS r")
    assert dec == [{"o": "rejected", "r": "not what the requirement asks"}]
    assert _one(conn, "MATCH (c:Change)-[:CHANGED]->(:Proposal {id: 'PR-009'}) RETURN c.action AS a") == [
        {"a": "reject_map"}]
    assert _covered_ids(conn) == before
    # memory: the same proposal is now refused, citing the new rejection
    again = P.create_proposal(conn, "map", "mapper-agent", ctrl, req, "second try")
    assert again["reason_code"] == "previously_rejected" and "not what the requirement asks" in again["verify_reason"]


def test_unverified_approve_is_refused_unless_forced(conn):
    bad = P.create_proposal(conn, "map", "mapper-agent", "CTRL-AOTP-11", "800-53:AC-17", "try again")  # S4
    assert bad["verified"] is False
    n_dec = _one(conn, "MATCH (d:Decision) RETURN count(d) AS n")[0]["n"]
    with pytest.raises(R.ReviewError, match="failed verification"):
        R.decide(conn, bad["id"], "approved", MAYA, "yes")
    assert _one(conn, "MATCH (d:Decision) RETURN count(d) AS n")[0]["n"] == n_dec  # nothing recorded
    assert _one(conn, "MATCH (p:Proposal {id: $id}) RETURN p.status AS s", id=bad["id"])[0]["s"] == "pending"
    assert _one(conn, "MATCH (:Control {id: 'CTRL-AOTP-11'})-[s:SATISFIES]->(:Requirement {id: '800-53:AC-17'}) "
                      "RETURN s") == []
    R.decide(conn, bad["id"], "approved", MAYA, "new evidence: the account review now covers VPN accounts", force=True)
    forced = _one(conn, "MATCH (d:Decision)-[:ON]->(:Proposal {id: $id}) RETURN d.forced AS f", id=bad["id"])
    assert forced == [{"f": True}]
    detail = _one(conn, "MATCH (c:Change)-[:CHANGED]->(:Proposal {id: $id}) RETURN c.detail AS d", id=bad["id"])[0]["d"]
    assert "FORCED" in detail and "previously_rejected" in detail
    assert _one(conn, "MATCH (:Control {id: 'CTRL-AOTP-11'})-[s:SATISFIES]->(:Requirement {id: '800-53:AC-17'}) "
                      "RETURN s.via_proposal AS v") == [{"v": bad["id"]}]


def test_seeded_pending_proposal_is_verified_when_decided(conn):
    pend = {p["id"]: p for p in R.pending(conn)}
    assert pend["PR-005"]["verified"] is None  # from the pack, never verified
    R.decide(conn, "PR-005", "rejected", MAYA, "SSO alone does not enforce MFA")
    row = _one(conn, "MATCH (p:Proposal {id: 'PR-005'}) RETURN p.verified AS v, p.verify_reason AS r, p.status AS s")[0]
    assert row["v"] is True and row["s"] == "rejected"


def test_decision_errors(conn):
    with pytest.raises(R.ReviewError, match="no proposal"):
        R.decide(conn, "PR-999", "approved", MAYA, "x")
    with pytest.raises(R.ReviewError, match="reason"):
        R.decide(conn, "PR-005", "rejected", MAYA, "  ")
    with pytest.raises(R.ReviewError, match="outcome"):
        R.decide(conn, "PR-005", "maybe", MAYA, "x")
    with pytest.raises(R.ReviewError, match="already approved"):
        R.decide(conn, "PR-003", "rejected", MAYA, "x")


def test_status_proposal_flow(conn):
    p = P.create_proposal(conn, "status", "evidence-agent", "CTRL-REAP-6", "at risk", "EV-044 expired")
    assert p["verified"] is True and p["target"] == "at_risk"
    assert _one(conn, "MATCH (p:Proposal {id: $id})-[:ABOUT]->(c:Control) RETURN c.id AS c, p.old_status AS o, "
                      "p.new_status AS n", id=p["id"]) == [{"c": "CTRL-REAP-6", "o": "implemented", "n": "at_risk"}]
    assert _one(conn, "MATCH (c:Control {id: 'CTRL-REAP-6'}) RETURN c.status AS s")[0]["s"] == "implemented"
    R.decide(conn, p["id"], "approved", MAYA, "evidence expired yesterday")
    assert _one(conn, "MATCH (c:Control {id: 'CTRL-REAP-6'}) RETURN c.status AS s")[0]["s"] == "at_risk"


def test_status_implemented_without_valid_evidence_is_flagged(conn):
    rows = _one(conn, "MATCH (c:Control {adopted: true}) WHERE c.status <> 'implemented' AND NOT EXISTS "
                      "{ MATCH (e:Evidence)-[:PROVES]->(c) WHERE e.expires_at > date('2026-12-02') } "
                      "RETURN c.id AS id ORDER BY id")
    if not rows:
        pytest.skip("every non-implemented control has valid evidence in this pack")
    p = P.create_proposal(conn, "status", "evidence-agent", rows[0]["id"], "implemented", "looks done")
    assert p["verified"] is False and p["reason_code"] == "implemented_without_evidence"


def test_evidence_request_flow_and_window(conn):
    p = P.create_proposal(conn, "evidence_request", "evidence-agent", "EV-044", "P-dana-okafor", "renew",
                          draft="Hi Dana, EV-044 (MFA setting screenshot) expired on 2026-12-01. Please re-capture it.")
    assert p["verified"] is True
    row = _one(conn, "MATCH (p:Proposal {id: $id})-[:ABOUT]->(e:Evidence) MATCH (p)-[:TARGET]->(x:Person) "
                     "RETURN e.id AS e, x.id AS x, p.draft AS d", id=p["id"])
    assert row[0]["e"] == "EV-044" and row[0]["x"] == "P-dana-okafor" and "re-capture" in row[0]["d"]
    soon = P.create_proposal(conn, "evidence_request", "evidence-agent", "EV-100", None, "renew")  # owner by default
    assert soon["verified"] is True and soon["target"]
    far = P.create_proposal(conn, "evidence_request", "evidence-agent", "EV-104", None, "renew")  # BP-06
    assert far["reason_code"] == "evidence_not_expiring"
    n_sat = _one(conn, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n")[0]["n"]
    R.decide(conn, p["id"], "approved", MAYA, "send it")
    assert _one(conn, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n")[0]["n"] == n_sat


def test_agents_cannot_propose_ownership_or_unknown_kinds(conn):
    with pytest.raises(P.ProposalError):
        P.create_proposal(conn, "ownership", "mapper-agent", "CTRL-MCP-13", "P-dana-okafor", "x")
    with pytest.raises(P.ProposalError):
        P.create_proposal(conn, "satisfies", "mapper-agent", "CTRL-MCP-13", "P-dana-okafor", "x")


def test_proposal_ids_continue_the_sequence(conn):
    ids = [P.create_proposal(conn, "status", "evidence-agent", "CTRL-REAP-6", "at_risk", f"n{i}")["id"]
           for i in range(2)]
    assert ids == ["PR-009", "PR-010"]
    assert _one(conn, "MATCH (p:Proposal {id: 'PR-009'})-[:BY]->(a:Agent) RETURN a.id AS a")[0]["a"] == "evidence-agent"


# --------------------------------------------------------------------------
# conflict retry (decide)
# --------------------------------------------------------------------------


class _Conflict(Exception):
    retryable = True


def test_decide_retries_once_on_a_retryable_conflict(conn, monkeypatch):
    real, calls = R._decide_once, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise _Conflict("write-write conflict")
        return real(*a, **k)

    monkeypatch.setattr(R, "_decide_once", flaky)
    assert R.decide(conn, "PR-005", "rejected", MAYA, "no").startswith("relate:")
    assert len(calls) == 2
    assert _one(conn, "MATCH (d:Decision)-[:ON]->(:Proposal {id: 'PR-005'}) RETURN count(d) AS n")[0]["n"] == 1


def test_decide_surfaces_a_clear_message_when_the_retry_also_conflicts(conn, monkeypatch):
    def always(*a, **k):
        raise _Conflict("write-write conflict")

    monkeypatch.setattr(R, "_decide_once", always)
    with pytest.raises(R.ReviewError, match="write-write conflict.*nothing was recorded"):
        R.decide(conn, "PR-005", "rejected", MAYA, "no")


# --------------------------------------------------------------------------
# concurrency demo
# --------------------------------------------------------------------------


def _assert_both_landed(res):
    assert res["errors"] == []
    assert res["both_landed"] and res["lost_updates"] == 0
    kinds = sorted(p["kind"] for p in res["proposals"])
    ids = [p["id"] for p in res["proposals"]]
    assert kinds == ["map", "status"] and len(set(ids)) == 2 and sorted(ids) == ["PR-009", "PR-010"]
    assert all(p["verified"] for p in res["proposals"])
    assert all(line.startswith("[") and "] " in line for line in res["log"])  # timestamped


def test_concurrency_embedded_lease_serialises_the_writers(store):
    res = demo.run_embedded(store, hold=0.5, delay=0.1, echo=False)
    _assert_both_landed(res)
    assert res["lock_waits"] >= 1 and res["conflicts"] == 0
    assert any("storage locked" in line for line in res["log"])
    assert any("COMMITTED PR-009" in line for line in res["log"])


def test_concurrency_served_store_conflicts_and_retries(store):
    try:
        B._relate_cli()
    except B.BuildError:
        pytest.skip("relate CLI not available")
    res = demo.run_server(store, hold_first=0.4, hold_second=0.8, delay=0.1, echo=False)
    _assert_both_landed(res)
    assert res["conflicts"] == 1
    assert any("write-write conflict" in line and "retryable=True" in line for line in res["log"])
    # the store is readable and complete after the server stopped
    c = relate.connect(str(store), read_only=True)
    try:
        assert {p["id"] for p in P.list_proposals(c, "pending")} >= {"PR-009", "PR-010"}
    finally:
        c.close()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_propose_review_decisions(store):
    from typer.testing import CliRunner

    from crosswalk.review_cli import app

    runner = CliRunner()
    # a fresh handle per command: each command opens and closes the store itself
    res = runner.invoke(app, ["propose-map", "CTRL-AOTP-11", "800-53:AC-17", "-r", "again", "--store", str(store), "--json"])
    assert res.exit_code == 0, res.output
    prop = json.loads(res.output)
    assert prop["id"] == "PR-009" and prop["verified"] is False and prop["reason_code"] == "previously_rejected"

    res = runner.invoke(app, ["review", "--approve", "PR-9", "--reason", "x", "--store", str(store)])
    assert res.exit_code == 1 and "failed verification" in res.output

    res = runner.invoke(app, ["review", "--reject", "PR-9", "--reason", "still local", "--store", str(store), "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["outcome"] == "rejected"

    res = runner.invoke(app, ["review", "--approve", "PR-003", "--store", str(store)])
    assert res.exit_code == 2 and "--reason" in res.output

    res = runner.invoke(app, ["decisions", "--about", "CTRL-AOTP-11", "--store", str(store), "--json"])
    rows = json.loads(res.output)
    assert [r["id"] for r in rows if r["proposal"] == "PR-009"] and rows[0]["id"] == "D-001"


def test_cli_interactive_review(store):
    from typer.testing import CliRunner

    from crosswalk.review_cli import app

    # PR-005 approve, PR-006 reject, PR-007 skip, then quit
    inp = "a\nSSO enforces MFA\nr\nIR-7 is assistance, not reporting\ns\nq\n"
    res = CliRunner().invoke(app, ["review", "--store", str(store), "--by", MAYA], input=inp)
    assert res.exit_code == 0, res.output
    c = relate.connect(str(store), read_only=True)
    try:
        status = {p["id"]: p["status"] for p in P.list_proposals(c)}
    finally:
        c.close()
    assert status["PR-005"] == "approved" and status["PR-006"] == "rejected" and status["PR-007"] == "pending"
