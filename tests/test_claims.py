"""Tests for crosswalk.claims (the claim checker), proposed paths, and the live-catch demo.

Everything runs on throw-away stores under tmp (built once per session, copied per test); nothing here
touches data/crosswalk.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import relate
from typer.testing import CliRunner

from crosswalk import build as B
from crosswalk import claims as C
from crosswalk import cli
from crosswalk import demo_live
from crosswalk import proposals as P
from crosswalk import queries as Q
from crosswalk import review as R
from crosswalk.paths import make_path

REPO = Path(__file__).resolve().parents[1]
REQ = "800-171:03.05.03"
EXPIRED_REASON = "EV-044 expired 2026-12-01"
PROPOSED_REASON = "mapping CTRL-PWP-4 -> 800-171:03.05.03 is proposed (PR-005), not approved"
CORRECTED = "Not covered. Renew EV-044 (owner Dana Okafor, request drafted) and review PR-005."


@pytest.fixture(scope="session")
def base_store(tmp_path_factory):
    store = tmp_path_factory.mktemp("claims-base") / "crosswalk"
    B.build(store, export=False)
    return store


@pytest.fixture(scope="module")
def pristine(base_store):
    conn = relate.connect(str(base_store), read_only=True)
    yield conn
    conn.close()


@pytest.fixture()
def store(base_store, tmp_path):
    dest = tmp_path / "crosswalk"
    shutil.copytree(base_store, dest)
    return dest


def _answer(*claims, **kw):
    return {"question": "q", "agent": "test-agent", "claims": list(claims), **kw}


def _claim(text, *ids, kind="coverage"):
    return {"text": text, "path_ids": list(ids), "kind": kind}


# --------------------------------------------------------------------------
# proposed paths
# --------------------------------------------------------------------------


def test_proposed_path_is_returned_and_checks_as_not_approved(pristine):
    rows = Q.proposed_paths(pristine, requirement=REQ)
    assert [r["proposal"] for r in rows] == ["PR-005"]
    row = rows[0]
    assert row["nodes"] == [f"Requirement:{REQ}", "Proposal:PR-005", "Control:CTRL-PWP-4"]
    assert row["rels"] == ["TARGET<-", "ABOUT"]
    res = Q.check_path(pristine, row["nodes"], row["rels"])
    assert res["exists"] and not res["valid"]
    assert res["problems"] == [PROPOSED_REASON]
    assert Q.explain(pristine, REQ)["proposed_paths"][0]["id"] == row["path_id"]


def test_recorded_answer_ids_are_the_ones_the_store_computes(pristine):
    rec = json.loads(demo_live.RECORDED.read_text(encoding="utf-8"))
    ex = Q.explain(pristine, REQ)
    assert rec["claims"][0]["path_ids"] == [ex["paths"][0]["path_id"]]
    assert rec["claims"][1]["path_ids"] == [ex["proposed_paths"][0]["id"]]
    assert make_path(rec["paths"][0]["nodes"], rec["paths"][0]["rels"])["id"] == rec["paths"][0]["id"]


# --------------------------------------------------------------------------
# the live catch
# --------------------------------------------------------------------------


def _live(base_store, draft=True):
    out = demo_live.run(base_store, draft=draft)
    out.pop("latency_ms")
    return out


def test_live_catch_yields_expired_ev044_and_proposed_pr005(base_store):
    out = _live(base_store)
    checked = out["checked"]
    assert checked["counts"] == {"claims": 2, "verified": 0, "partial": 1, "failed": 1, "paths": 2, "paths_ok": 0}
    expired, proposed = checked["claims"]
    assert (expired["symbol"], expired["verdict"], expired["codes"]) == ("✖", "failed", ["expired_evidence"])
    assert expired["paths"][0]["reason"] == EXPIRED_REASON
    assert (proposed["symbol"], proposed["verdict"], proposed["codes"]) == ("⚠", "partial", ["proposed_mapping"])
    assert proposed["paths"][0]["reason"] == PROPOSED_REASON
    assert out["corrected"]["text"] == CORRECTED
    assert [d["evidence"] for d in out["drafts"]] == ["EV-044"] and out["drafts"][0]["to"] == "P-dana-okafor"


def test_live_catch_is_identical_ten_times_and_leaves_the_store_alone(base_store):
    before = {f.name: f.stat().st_size for f in base_store.iterdir() if f.is_file()}
    runs = [json.dumps(_live(base_store), sort_keys=True) for _ in range(10)]
    assert len(set(runs)) == 1
    assert {f.name: f.stat().st_size for f in base_store.iterdir() if f.is_file()} == before
    conn = relate.connect(str(base_store), read_only=True)
    try:
        assert conn.execute("MATCH (p:Proposal) RETURN count(p) AS n").fetchall()[0]["n"] == 8  # no PR-009 here
    finally:
        conn.close()


def test_live_catch_is_fast(base_store):
    assert demo_live.run(base_store, draft=False)["latency_ms"] < 1000


def test_cli_demo_and_check(base_store, tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli.app, ["demo", "live-catch", "--store", str(base_store)])
    assert res.exit_code == 0, res.output
    assert "✖ 03.05.03 is covered by CTRL-REAP-6" in res.output
    assert f"✖ P-94fd053fec24  {EXPIRED_REASON}" in res.output
    assert f"⚠ P-1a53bde4375b  {PROPOSED_REASON}" in res.output
    assert CORRECTED in res.output
    f = tmp_path / "a.json"
    f.write_text(json.dumps(_answer(_claim("x", "P-94fd053fec24"), _claim("y", "P-deadbeef0000"), {"text": "z"})))
    res = runner.invoke(cli.app, ["check", str(f), "--store", str(base_store), "--json"])
    assert res.exit_code == 1
    data = json.loads(res.output)
    assert [c["verdict"] for c in data["claims"]] == ["failed", "failed", "failed"]


# --------------------------------------------------------------------------
# verdicts
# --------------------------------------------------------------------------


def test_every_explain_path_verifies(pristine):
    """Each explain path that says valid re-runs as verified; the others fail with a stated reason."""
    reqs = [r["id"] for r in pristine.execute(
        "MATCH (r:Requirement) WHERE (r)<-[:SATISFIES]-() RETURN r.id AS id").fetchall()]
    assert len(reqs) > 50
    reg = C.PathRegistry()
    checked_valid = checked_invalid = 0
    for rid in reqs:
        ex = Q.explain(pristine, rid)
        reg.register_result(ex, "explain")
        paths = ex["paths"] + ex["inherited_paths"]
        claims = [_claim(f"{rid} via {p['path_id'] if 'path_id' in p else p['id']}",
                         p.get("path_id") or p["id"]) for p in paths]
        if not claims:
            continue
        out = C.check_claims(pristine, _answer(*claims), reg)
        for p, c in zip(paths, out["claims"]):
            if p.get("valid", True) and p.get("evidence") is not None:
                assert c["verdict"] == "verified", (rid, c)
                checked_valid += 1
            else:
                assert c["verdict"] == "failed" and c["reason"], (rid, c)
                checked_invalid += 1
    assert checked_valid > 40 and checked_invalid >= 1


def test_fabricated_id_fails_as_unknown(pristine):
    out = C.check_claims(pristine, _answer(_claim("made up", "P-0123456789ab")), C.PathRegistry())
    c = out["claims"][0]
    assert c["verdict"] == "failed" and c["codes"] == ["unknown_path"]
    assert c["reason"].startswith("uncited/unknown path")
    assert c["paths"][0]["nodes"] is None


def test_claim_with_no_path_has_no_receipt(pristine):
    out = C.check_claims(pristine, _answer({"text": "trust me"}, {"text": "also", "path_ids": []}), C.PathRegistry())
    for c in out["claims"]:
        assert c["verdict"] == "failed" and c["codes"] == ["no_receipt"]
        assert c["reason"].startswith("no receipt")
    assert out["counts"]["failed"] == 2


def test_valid_path_is_verified_and_summary_counts(pristine):
    ex = Q.explain(pristine, "800-171:03.01.05")
    good = next(p["path_id"] for p in ex["paths"] if p["valid"])
    out = C.check_claims(pristine, _answer(_claim("covered", good), _claim("also covered", good)), C.PathRegistry())
    assert out["summary"] == "2/2 claims verified"
    assert out["counts"] == {"claims": 2, "verified": 2, "partial": 0, "failed": 0, "paths": 1, "paths_ok": 1}
    assert C.corrected_answer(pristine, out)["text"] == "All 2 claims verified."


def test_ids_only_answer_works_in_a_fresh_process_via_discovery(pristine):
    reg = C.PathRegistry()
    assert len(reg) == 0
    out = C.check_claims(pristine, _answer(_claim("x", "P-94fd053fec24"), _claim("y", "P-1a53bde4375b")), reg)
    assert [c["codes"] for c in out["claims"]] == [["expired_evidence"], ["proposed_mapping"]]
    assert reg.discovered and len(reg) > 1000


def test_inline_receipts_must_match_their_id(pristine):
    real = make_path([f"Requirement:{REQ}", "Control:CTRL-REAP-6", "Evidence:EV-044"], ["SATISFIES<-", "PROVES<-"])
    forged = {"id": "P-aaaaaaaaaaaa", **{k: real[k] for k in ("nodes", "rels")}}
    reg = C.PathRegistry()
    reg.discovered = True  # no discovery: only inline receipts could help
    out = C.check_claims(pristine, _answer(_claim("x", "P-aaaaaaaaaaaa"), paths=[forged]), reg)
    assert out["claims"][0]["codes"] == ["unknown_path"]
    out = C.check_claims(pristine, _answer(_claim("x", real["id"]), paths=[real]), reg)
    assert out["claims"][0]["codes"] == ["expired_evidence"]


def test_mapping_without_evidence_is_not_coverage(pristine):
    p = make_path([f"Requirement:{REQ}", "Control:CTRL-REAP-6"], ["SATISFIES<-"])
    reg = C.PathRegistry()
    reg.register(p["nodes"], p["rels"])
    cov = C.check_claims(pristine, _answer(_claim("covered", p["id"])), reg)["claims"][0]
    assert cov["verdict"] == "failed" and cov["codes"] == ["no_evidence"]
    fact = C.check_claims(pristine, _answer(_claim("mapped", p["id"], kind="fact")), reg)["claims"][0]
    assert fact["verdict"] == "verified"


def test_broken_structure_and_mixed_claim(pristine):
    reg = C.PathRegistry()
    broken = reg.register([f"Requirement:{REQ}", "Control:CTRL-PWP-4", "Evidence:EV-001"], ["SATISFIES<-", "PROVES<-"])
    ex = Q.explain(pristine, "800-171:03.01.05")
    good = next(p["path_id"] for p in ex["paths"] if p["valid"])
    reg.register_result(ex)
    out = C.check_claims(pristine, _answer(_claim("broken", broken), _claim("mixed", good, broken)), reg)
    first, mixed = out["claims"]
    assert first["codes"] == ["broken_structure"] and first["verdict"] == "failed"
    assert first["paths"][0]["reason"].startswith("broken path: no SATISFIES<- relationship")
    assert mixed["verdict"] == "partial" and mixed["codes"] == ["broken_structure"]


def test_rejected_and_unadopted_proposals(store):
    w = P.open_writer(store)
    try:
        # CTRL-AOTP-5 is in the library but not adopted: the proposal is stored, its path is not citable as coverage
        unadopted = P.create_proposal(w, "map", "mapper-agent", "CTRL-AOTP-5", "800-53:AC-2", "account approval")
        pend = P.create_proposal(w, "map", "mapper-agent", "CTRL-WP-1", "800-53:CM-6", "baseline settings")
        R.decide(w, pend["id"], "rejected", "P-maya-chen", "not baseline configuration")
    finally:
        w.close()
    conn = relate.connect(str(store), read_only=True)
    try:
        rows = {r["proposal"]: r for r in Q.proposed_paths(conn, status=None)}
        out = C.check_claims(conn, _answer(_claim("a", rows[unadopted["id"]]["path_id"]),
                                           _claim("b", rows[pend["id"]]["path_id"])), C.PathRegistry())
    finally:
        conn.close()
    a, b = out["claims"]
    assert a["codes"] == ["not_adopted"] and "control CTRL-AOTP-5 is not adopted" in a["paths"][0]["reason"]
    assert b["codes"] == ["rejected_mapping"] and "was rejected (" in b["paths"][0]["reason"]


def test_approved_proposal_path_and_satisfies_path_verify(store):
    w = P.open_writer(store)
    try:
        # CTRL-AOTP-8 already has valid evidence; approving a mapping to a new requirement makes it coverage
        pr = P.create_proposal(w, "map", "mapper-agent", "CTRL-AOTP-8", "800-53:AC-2", "account management")
        R.decide(w, pr["id"], "approved", "P-maya-chen", "ok", force=True)
    finally:
        w.close()
    conn = relate.connect(str(store), read_only=True)
    try:
        ex = Q.explain(conn, "800-53:AC-2")
        path = next(p for p in ex["paths"] if p["control"] == "CTRL-AOTP-8" and p["valid"])
        proposal = next(p for p in ex["proposals"] if p["proposal"] == pr["id"])
        reg = C.PathRegistry()
        reg.register_result(ex)
        out = C.check_claims(conn, _answer(_claim("covered", path["path_id"]), _claim("proposed", proposal["path_id"],
                                                                                 kind="fact")), reg)
    finally:
        conn.close()
    assert [c["verdict"] for c in out["claims"]] == ["verified", "verified"]


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------


def test_persist_writes_answer_claims_and_paths(store):
    rec = json.loads(demo_live.RECORDED.read_text(encoding="utf-8"))
    conn = relate.connect(str(store), read_only=True)
    try:
        checked = C.check_claims(conn, rec, C.PathRegistry())
        checked["claims"].append({**checked["claims"][0], "index": 3, "text": "no id", "paths": [], "path_ids": [],
                                  "verdict": "failed", "symbol": "✖", "verified": False, "reason": "no receipt",
                                  "reasons": ["no receipt"], "codes": ["no_receipt"]})
        checked["counts"]["claims"] = 3
    finally:
        conn.close()
    w = P.open_writer(store)
    try:
        res = C.persist(w, checked)
    finally:
        w.close()
    assert res["answer"] == "ANS-001"
    conn = relate.connect(str(store), read_only=True)
    try:
        rows = [dict(r) for r in conn.execute(
            "MATCH (a:Answer)-[:HAS_CLAIM]->(c:Claim)-[:CITES]->(p:Path) "
            "RETURN a.id AS a, c.verdict AS v, c.verified AS ok, c.reason AS why, p.id AS p, p.nodes AS nodes "
            "ORDER BY p").fetchall()]
        assert [(r["a"], r["v"], r["ok"], r["p"]) for r in rows] == [
            ("ANS-001", "partial", False, "P-1a53bde4375b"), ("ANS-001", "failed", False, "P-94fd053fec24")]
        assert rows[1]["why"] == EXPIRED_REASON
        assert conn.execute("MATCH (c:Claim) RETURN count(c) AS n").fetchall()[0]["n"] == 3
        # a later process can resolve the id from the graph alone (no discovery)
        reg = C.PathRegistry()
        reg.discovered = True
        got = C.check_claims(conn, _answer(_claim("x", "P-94fd053fec24")), reg)
        assert got["claims"][0]["codes"] == ["expired_evidence"]
        assert reg.get("P-94fd053fec24")["source"] == "graph"
    finally:
        conn.close()
