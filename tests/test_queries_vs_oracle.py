"""Cypher answers (queries/*.cypher via crosswalk.queries) against eval/ground_truth.json.

Comparisons are at ID-SET level (which requirements, controls, evidence, neighbours, audits, people),
not just counts.  The oracle is pure Python; nothing here reads the YAML inputs except through the
ground-truth file and the NIST baseline membership (for the baseline-scoped audit).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
import relate
from typer.testing import CliRunner

from crosswalk import build as B
from crosswalk import paths as P
from crosswalk import queries as Q
from crosswalk.cli import app
from crosswalk.sources import nist

ROOT = Path(__file__).resolve().parent.parent
GT = json.loads((ROOT / "eval" / "ground_truth.json").read_text(encoding="utf-8"))
FRAMEWORKS = ["800-53", "800-171", "CSF"]
AUDITS = sorted(GT["q1_coverage"]["by_audit"])


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    d = tmp_path_factory.mktemp("qstore") / "crosswalk"
    B.build(d, export=False)
    return d


@pytest.fixture(scope="module")
def conn(store):
    c = relate.connect(str(store), read_only=True)
    yield c
    c.close()


def ids(rows, status):
    return {r["id"] for r in rows if r["status"] == status}


def next_day(date: str, n: int = 1) -> str:
    return (dt.date.fromisoformat(date) + dt.timedelta(days=n)).isoformat()


def all_paths_ok(conn, paths, as_of=None):
    """Every {nodes, rels} path exists and is valid; returns how many were checked."""
    for p in paths:
        c = Q.check_path(conn, p["nodes"], p["rels"], as_of)
        assert c["exists"] and c["valid"], (p, c)
        assert c["path_id"] == p["id"]
    return len(paths)


# --------------------------------------------------------------------------
# path ids
# --------------------------------------------------------------------------


def test_path_id_format_and_canonical_string():
    nodes = ["Requirement:800-171:03.01.01", "Control:CTRL-AOTP-8", "Evidence:EV-012"]
    rels = ["SATISFIES<-", "PROVES<-"]
    canon = "Requirement:800-171:03.01.01|SATISFIES<-|Control:CTRL-AOTP-8|PROVES<-|Evidence:EV-012"
    assert P.canonical(nodes, rels) == canon
    expected = "P-" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]
    assert P.path_id(nodes, rels) == expected
    assert len(expected) == 14


def test_path_id_deterministic_and_discriminating():
    nodes = ["Requirement:800-53:AC-2", "Control:CTRL-AOTP-8", "Evidence:EV-001"]
    rels = ["SATISFIES<-", "PROVES<-"]
    assert P.path_id(nodes, rels) == P.path_id(list(nodes), list(rels))
    assert P.path_id(nodes, rels) != P.path_id(nodes[::-1], ["PROVES", "SATISFIES"])
    assert P.path_id(nodes, rels) != P.path_id(nodes, ["SATISFIES", "PROVES<-"])
    assert P.path_id(nodes, rels) != P.path_id(nodes[:2], rels[:1])
    # symmetric crosswalk links ignore the direction mark
    a = ["Requirement:800-171:03.01.01", "Requirement:800-53:AC-2"]
    assert P.path_id(a, ["EQUIVALENT_TO"]) == P.path_id(a, ["EQUIVALENT_TO<-"])
    with pytest.raises(ValueError):
        P.path_id(nodes, rels[:1])
    with pytest.raises(ValueError):
        P.path_id(["nolabel"], [])


def test_query_path_ids_are_stable_across_runs(conn):
    a = Q.explain(conn, "800-171:03.05.03")
    b = Q.explain(conn, "800-171:03.05.03")
    assert [p["path_id"] for p in a["paths"]] == [p["path_id"] for p in b["paths"]]
    first = a["paths"][0]
    assert first["path_id"] == P.path_id(first["nodes"], first["rels"])


# --------------------------------------------------------------------------
# Q1 coverage
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fw", FRAMEWORKS)
def test_q1_framework_id_sets(conn, fw):
    exp = GT["q1_coverage"]["by_framework"][fw]
    res = Q.coverage(conn, fw)
    reqs = res["requirements"]
    assert res["as_of"] == GT["as_of"]
    assert ids(reqs, "covered") == set(exp["covered_direct"])
    assert ids(reqs, "inherited") == set(exp["inherited"])
    assert ids(reqs, "gap") == set(exp["gap"])
    assert (res["covered"], res["inherited"], res["gaps"], res["total"]) == (
        exp["counts"]["direct"], exp["counts"]["inherited"], exp["counts"]["gap"], exp["active_requirements"])


@pytest.mark.parametrize("fw", FRAMEWORKS)
def test_q1_rows_carry_valid_paths(conn, fw):
    rows = Q.coverage(conn, fw)["requirements"]
    checked = 0
    for r in rows:
        if r["status"] == "gap":
            assert r["paths"] == []
            continue
        assert r["paths"], r["id"]
        for p in r["paths"][:2]:  # two receipts per row keep the run short
            assert p["nodes"][0] == f"Requirement:{r['id']}"
            checked += all_paths_ok(conn, [p])
        if r["status"] == "covered":
            assert {p["nodes"][1] for p in r["paths"]} == {f"Control:{c}" for c in r["controls"]}
        else:
            assert {p["nodes"][1] for p in r["paths"]} == {f"Requirement:{v}" for v in r["via"]}
    assert checked


@pytest.mark.parametrize("audit", AUDITS)
def test_q1_audit_id_sets(conn, audit):
    exp = GT["q1_coverage"]["by_audit"][audit]
    fw = exp["framework"]
    fw_exp = GT["q1_coverage"]["by_framework"][fw]
    res = Q.coverage(conn, audit=audit)
    scope = None
    if exp["scope_baseline"]:
        scope = nist.load_baseline(name=exp["scope_baseline"])
    def keep(rids):
        return {r for r in rids if scope is None or r in scope}
    reqs = res["requirements"]
    assert {r["id"] for r in reqs} == keep(fw_exp["covered_direct"] + fw_exp["inherited"] + fw_exp["gap"])
    assert ids(reqs, "covered") == keep(fw_exp["covered_direct"])
    assert ids(reqs, "inherited") == keep(fw_exp["inherited"])
    assert ids(reqs, "gap") == keep(fw_exp["gap"])
    assert res["total"] == exp["scope_requirements"]
    assert {"direct": res["covered"], "inherited": res["inherited"], "gap": res["gaps"]} == exp["counts"]


# --------------------------------------------------------------------------
# Q2 adopt
# --------------------------------------------------------------------------


def _via_map(item):
    return {v["neighbour"]: {c["control"]: set(c["evidence"]) for c in v["controls"]} for v in item["via"]}


@pytest.mark.parametrize("fw", ["800-171", "CSF"])
def test_q2_adopt_ids_neighbours_controls_evidence(conn, fw):
    exp = GT["q2_adopt"][fw]
    res = Q.adopt(conn, fw)
    assert res["inherited_count"] == exp["inherited_count"]
    assert res["active_requirements"] == exp["active_requirements"]
    got = {i["requirement"]: i for i in res["inherited"]}
    want = {i["requirement"]: i for i in exp["inherited"]}
    assert set(got) == set(want)
    for rid, item in want.items():
        assert _via_map(got[rid]) == _via_map(item), rid
        assert got[rid]["paths"], rid
        assert all_paths_ok(conn, got[rid]["paths"][:2])


def test_q2_adopt_800_53_has_no_inheritance(conn):
    res = Q.adopt(conn, "800-53")
    assert res["inherited"] == [] and res["inherited_count"] == 0


def test_q2_adopt_matches_q1_inherited(conn):
    for fw in ("800-171", "CSF"):
        assert {i["requirement"] for i in Q.adopt(conn, fw)["inherited"]} == ids(
            Q.coverage(conn, fw)["requirements"], "inherited")


# --------------------------------------------------------------------------
# Q3 blast radius
# --------------------------------------------------------------------------


def assert_blast_equal(res, exp):
    assert res["as_of"] == exp["as_of"]
    assert res["cutoff"] == exp["cutoff"]
    assert res["window_days"] == exp["window_days"]
    assert res["affected_audit_rule"] == exp["affected_audit_rule"]
    # expiring evidence
    got = {e["evidence"]: e for e in res["expiring_evidence"]}
    want = {e["evidence"]: e for e in exp["expiring_evidence"]}
    assert set(got) == set(want)
    for i, w in want.items():
        g = got[i]
        assert g["expires_at"] == w["expires_at"]
        for k in ("proves", "controls_left_without_valid_evidence", "controls_with_replacement", "requested_by"):
            assert set(g[k]) == set(w[k]), (i, k)
    assert set(res["controls_left_without_valid_evidence"]) == set(exp["controls_left_without_valid_evidence"])
    # broken requirements, controls, still_inherited flags
    got_b = {b["requirement"]: b for b in res["broken_requirements"]}
    want_b = {b["requirement"]: b for b in exp["broken_requirements"]}
    assert set(got_b) == set(want_b)
    for r, w in want_b.items():
        g = got_b[r]
        assert g["framework"] == w["framework"]
        assert set(g["controls_lost"]) == set(w["controls_lost"]), r
        assert g["still_inherited"] == w["still_inherited"], r
        assert set(g["inherited_via"]) == set(w["inherited_via"]), r
        assert bool(g["inherited_paths"]) == w["still_inherited"], r
        assert g["paths"], r
    assert res["broken_counts"] == exp["broken_counts"]
    for fw in FRAMEWORKS:
        assert set(res["broken_by_framework"][fw]) == set(exp["broken_by_framework"][fw])
    assert set(res["broken_and_not_inherited"]) == set(exp["broken_and_not_inherited"])
    # affected audits (rule: requests an expiring item OR framework has a broken requirement)
    got_a = {a["audit"]: a for a in res["affected_audits"]}
    want_a = {a["audit"]: a for a in exp["affected_audits"]}
    assert set(got_a) == set(want_a)
    for a, w in want_a.items():
        g = got_a[a]
        assert set(g["requests_expiring_evidence"]) == set(w["requests_expiring_evidence"])
        assert g["broken_requirements_in_framework"] == w["broken_requirements_in_framework"]
        assert g["framework"] == w["framework"] and g["date"] == w["date"]
        assert g["days_after_as_of"] == w["days_after_as_of"]


def test_q3_blast_30_days(conn):
    res = Q.blast(conn, days=30)
    assert_blast_equal(res, GT["q3_blast_30d"])
    assert res["broken_counts"]["800-171"] == 6  # EV-100 + EV-102 (S2)


@pytest.mark.parametrize("audit", AUDITS)
def test_q3_blast_until_audit(conn, audit):
    exp = GT["q3_blast_until_audit"][audit]
    assert_blast_equal(Q.blast(conn, audit=audit), exp)
    assert_blast_equal(Q.blast(conn, until=exp["cutoff"]), exp)


def test_q3_s2_split_and_decoy(conn):
    res = Q.blast(conn, audit="AUD-171")
    c171 = res["broken_by_framework"]["800-171"]
    assert len(c171) == 9
    assert {r for r in c171 if r in res["broken_and_not_inherited"]} == {
        "800-171:03.03.05", "800-171:03.10.02", "800-171:03.11.02", "800-171:03.12.01"}
    # S6 decoy: EV-017 expired on 2026-10-01 with replacement EV-016, never flagged
    assert "EV-017" not in {e["evidence"] for e in res["expiring_evidence"]}
    assert all("CTRL-ASP-19" not in b["controls_lost"] for b in res["broken_requirements"])


def test_q3_paths_are_valid_now_and_dead_after_cutoff(conn):
    res = Q.blast(conn, audit="AUD-171")
    cutoff = res["cutoff"]
    n = 0
    for b in res["broken_requirements"]:
        n += all_paths_ok(conn, b["paths"])  # covered today
        for p in b["paths"]:
            assert not Q.check_path(conn, p["nodes"], p["rels"], as_of=cutoff)["valid"], p
        n += all_paths_ok(conn, b["inherited_paths"], as_of=cutoff)  # survivors still hold at cutoff
    assert n > 14


# --------------------------------------------------------------------------
# Q4 reuse
# --------------------------------------------------------------------------


def test_q4_reuse_full_ranking(conn):
    exp = GT["q4_reuse"]
    res = Q.reuse(conn)
    assert [r["evidence"] for r in res] == [r["evidence"] for r in exp]  # full order
    assert [r["rank"] for r in res] == [r["rank"] for r in exp]
    for g, w in zip(res, exp):
        e = w["evidence"]
        assert set(g["controls"]) == set(w["controls"]), e
        assert set(g["direct_requirements"]) == set(w["direct_requirements"]), e
        assert set(g["one_hop_requirements"]) == set(w["one_hop_requirements"]), e
        assert g["frameworks_direct"] == w["frameworks_direct"], e
        assert g["frameworks_reached"] == w["frameworks_reached"], e
        assert (g["direct_count"], g["framework_count"], g["reach_count"]) == (
            w["direct_count"], w["framework_count"], w["reach_count"]), e
        assert len(g["paths"]) >= w["direct_count"] or w["direct_count"] == 0
        assert len(g["paths_one_hop"]) >= len(w["one_hop_requirements"])


def test_q4_top_and_s7(conn):
    top = Q.reuse(conn, top=3)
    assert [r["evidence"] for r in top] == [r["evidence"] for r in GT["q4_reuse"][:3]]
    assert top[0]["evidence"] == "EV-065" and top[0]["frameworks_reached"] == FRAMEWORKS
    all_paths_ok(conn, top[0]["paths"])


# --------------------------------------------------------------------------
# Q6 owner risk
# --------------------------------------------------------------------------


def test_q6_owner_risk_people_and_unowned(conn):
    exp = GT["q6_owner_risk"]
    res = Q.owner_risk(conn)
    assert set(res["people"]) == set(exp["people"])
    for pid, w in exp["people"].items():
        g = res["people"][pid]
        assert g["name"] == w["name"]
        assert g["sole_owned_count"] == w["sole_owned_count"], pid
        for k in ("controls_solely_owned", "requirements_mapped", "requirements_solely_dependent",
                  "systems_touched", "high_criticality_systems", "controls_touching_high_systems"):
            assert set(g[k]) == set(w[k]), (pid, k)
    assert set(res["unowned_controls"]) == set(exp["unowned_controls"]) == {"CTRL-MCP-13"}
    assert res["sole_owner_ranking"] == exp["sole_owner_ranking"]


def test_q6_s3_dana_and_receipts(conn):
    res = Q.owner_risk(conn)
    dana = res["people"]["P-dana-okafor"]
    assert dana["sole_owned_count"] == 6 and len(dana["controls_touching_high_systems"]) == 6
    assert dana["audits_affected"]
    assert len(dana["paths"]) == 6
    all_paths_ok(conn, dana["paths"])
    all_paths_ok(conn, dana["dependency_paths"][:5])


# --------------------------------------------------------------------------
# explain
# --------------------------------------------------------------------------

EXPLAIN_IDS = sorted(GT["explain"])


def _path_key(p):
    return (p["control"], p.get("evidence"), p.get("collected_at"), p.get("expires_at"),
            p["mapping_approved_by"], p["mapping_approved_at"], p["valid"])


def test_explain_ground_truth_covers_all_171(conn):
    assert len(EXPLAIN_IDS) >= 97
    assert len([r for r in EXPLAIN_IDS if r.startswith("800-171:")]) == 97


def test_explain_every_requirement(conn):
    for rid in EXPLAIN_IDS:
        exp = GT["explain"][rid]
        res = Q.explain(conn, rid)
        assert res["requirement"] == rid
        assert res["covered_direct"] == exp["covered_direct"], rid
        assert res["inherited"] == exp["inherited"], rid
        assert set(res["inherited_via"]) == set(exp["inherited_via"]), rid
        assert set(res["proposed_only"]) == set(exp["proposed_only"]), rid
        assert {_path_key(p) for p in res["paths"]} == {_path_key(p) for p in exp["paths"]}, rid
        assert len(res["paths"]) == len(exp["paths"]), rid
        if exp["inherited"]:
            assert res["inherited_paths"], rid
            assert {p["neighbour"] for p in res["inherited_paths"]} == set(exp["inherited_via"])


def test_explain_s1_live_catch(conn):
    res = Q.explain(conn, "800-171:03.05.03")
    assert not res["covered_direct"] and not res["inherited"]
    (p,) = res["paths"]
    assert (p["control"], p["evidence"], p["expires_at"], p["valid"]) == ("CTRL-REAP-6", "EV-044", "2026-12-01", False)
    assert res["proposed_only"] == ["CTRL-PWP-4"]
    c = Q.check_path(conn, p["nodes"], p["rels"])
    assert c["exists"] and not c["valid"] and "expired" in " ".join(c["problems"])
    # the proposed mapping is not a SATISFIES path at all
    prop = Q.check_path(conn, ["Requirement:800-171:03.05.03", "Control:CTRL-PWP-4"], ["SATISFIES<-"])
    assert not prop["exists"] and not prop["valid"]


def test_explain_unknown_requirement(conn):
    with pytest.raises(LookupError):
        Q.explain(conn, "800-171:99.99.99")
    assert Q.resolve_requirement(conn, "03.05.03") == "800-171:03.05.03"
    assert Q.resolve_requirement(conn, "ac-2(1)") == "800-53:AC-2(1)"


# --------------------------------------------------------------------------
# check_path
# --------------------------------------------------------------------------


def test_check_path_true_for_every_explain_path_and_false_after_expiry(conn):
    as_of = GT["as_of"]
    n_valid = n_all = 0
    for rid in EXPLAIN_IDS:
        res = Q.explain(conn, rid)
        for p in res["paths"] + res["inherited_paths"]:
            nodes, rels = p["nodes"], p["rels"]
            now = Q.check_path(conn, nodes, rels)
            assert now["exists"], p
            assert now["path_id"] == p.get("path_id", p.get("id"))
            n_all += 1
            if "valid" in p and not p["valid"]:
                if p["evidence"] is not None:  # expired evidence on the path
                    assert not now["valid"] and now["problems"], p
                else:  # control with no evidence at all: the 2-node path itself is intact
                    assert len(p["nodes"]) == 2
                continue
            assert now["valid"], (rid, p, now)
            n_valid += 1
            if nodes[-1].startswith("Evidence:"):
                exp = p["expires_at"]
                assert Q.check_path(conn, nodes, rels, as_of=next_day(exp, -1))["valid"], p  # last valid day
                late = Q.check_path(conn, nodes, rels, as_of=exp)  # expires_at > as_of must fail
                assert late["exists"] and not late["valid"], p
                assert not Q.check_path(conn, nodes, rels, as_of=next_day(exp, 30))["valid"]
    assert n_valid > 40 and n_all > n_valid


def test_check_path_fabricated_and_wrong_shape(conn):
    # real nodes but no such link
    assert not Q.check_path(conn, ["Requirement:800-171:03.05.03", "Control:CTRL-AOTP-8", "Evidence:EV-065"],
                            ["SATISFIES<-", "PROVES<-"])["exists"]
    # ids that do not exist
    c = Q.check_path(conn, ["Requirement:800-171:03.05.03", "Control:CTRL-NOPE-1", "Evidence:EV-999"],
                     ["SATISFIES<-", "PROVES<-"])
    assert not c["exists"] and not c["valid"] and c["problems"]
    # right nodes, wrong direction marks
    good = ["Requirement:800-171:03.05.03", "Control:CTRL-REAP-6"]
    assert Q.check_path(conn, good, ["SATISFIES<-"])["exists"]
    assert not Q.check_path(conn, good, ["SATISFIES"])["exists"]
    # right ids, wrong label
    assert not Q.check_path(conn, ["Control:800-171:03.05.03", "Control:CTRL-REAP-6"], ["SATISFIES<-"])["exists"]
    # right ids, wrong relationship type
    assert not Q.check_path(conn, good, ["OWNS<-"])["exists"]
    # half real, half fabricated is not a path
    assert not Q.check_path(conn, ["Requirement:800-171:03.05.03", "Control:CTRL-REAP-6", "Evidence:EV-065"],
                            ["SATISFIES<-", "PROVES<-"])["exists"]
    with pytest.raises(ValueError):
        Q.check_path(conn, good, ["SATISFIES<-", "PROVES<-"])


def test_check_path_unadopted_control_and_symmetric_crosswalk(conn):
    # CTRL-AOTP-4 is in the library but not adopted: it has no SATISFIES at all
    assert not Q.check_path(conn, ["Control:CTRL-AOTP-4", "Requirement:800-53:AC-17"], ["SATISFIES"])["exists"]
    # an explain-inherited path survives either stored direction of EQUIVALENT_TO
    it = Q.adopt(conn, "800-171")["inherited"][0]
    p = it["paths"][0]
    assert Q.check_path(conn, p["nodes"], p["rels"])["valid"]
    assert Q.check_path(conn, p["nodes"], ["EQUIVALENT_TO<-"] + p["rels"][1:])["exists"]


# --------------------------------------------------------------------------
# CLI (--json on every command, against the throwaway store)
# --------------------------------------------------------------------------


def _cli(store, *args):
    r = CliRunner().invoke(app, [*args, "--json", "--store", str(store)])
    assert r.exit_code == 0, r.output
    return json.loads(r.output)


def test_cli_json_outputs_match_oracle(store):
    adopt = _cli(store, "adopt", "800-171")
    assert {i["requirement"] for i in adopt["inherited"]} == {i["requirement"] for i in GT["q2_adopt"]["800-171"]["inherited"]}
    b30 = _cli(store, "blast", "--days", "30")
    assert b30["broken_counts"] == GT["q3_blast_30d"]["broken_counts"]
    baud = _cli(store, "blast", "--audit", "AUD-171")
    assert baud["cutoff"] == "2027-01-15" and baud["broken_counts"]["800-171"] == 9
    buntil = _cli(store, "blast", "--until", "2027-01-15")
    assert buntil["broken_counts"] == baud["broken_counts"]
    reuse = _cli(store, "reuse", "--top", "4")
    assert [r["evidence"] for r in reuse] == [r["evidence"] for r in GT["q4_reuse"][:4]]
    owners = _cli(store, "owners")
    assert owners["unowned_controls"] == ["CTRL-MCP-13"]
    ex = _cli(store, "explain", "03.05.03")
    assert ex["requirement"] == "800-171:03.05.03" and not ex["covered_direct"]


def test_cli_tables_and_markdown_render(store):
    runner = CliRunner()
    for args in (["adopt", "CSF"], ["blast", "--audit", "AUD-171"], ["reuse", "--top", "3"], ["owners"],
                 ["explain", "800-171:03.05.03"]):
        r = runner.invoke(app, [*args, "--store", str(store)])
        assert r.exit_code == 0, (args, r.output)
    r = runner.invoke(app, ["explain", "800-171:03.05.03", "--md", "--store", str(store)])
    assert r.exit_code == 0 and "**GAP**" in r.output and "EV-044" in r.output and "P-94fd053fec24" in r.output
    bad = runner.invoke(app, ["blast", "--until", "2027-01-15", "--audit", "AUD-171", "--store", str(store)])
    assert bad.exit_code == 1
    assert runner.invoke(app, ["explain", "800-171:99.99.99", "--store", str(store)]).exit_code == 1
