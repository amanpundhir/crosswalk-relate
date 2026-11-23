"""One test per planted scenario (S1..S8), asserted against the pure-Python oracle.

Expected facts live in eval/planted.yaml; the oracle computes the actual values.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_oracle():
    spec = importlib.util.spec_from_file_location("crosswalk_oracle", ROOT / "eval" / "oracle.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["crosswalk_oracle"] = mod
    spec.loader.exec_module(mod)
    return mod


o = _load_oracle()
P = yaml.safe_load((ROOT / "eval" / "planted.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def w():
    return o.world()


def test_as_of_comes_from_pack(w):
    assert w["as_of"].isoformat() == P["as_of"] == "2026-12-02"


def test_s1_live_catch(w):
    s = P["S1"]
    req, ctrl, ev = s["requirement"], s["control"], s["evidence"]
    covered = o.direct_coverage()
    assert req not in covered
    assert o.inherited_via(req, covered) == []
    # the sole evidence of the MFA control expired the day before as_of
    assert w["proves"][ctrl] == [ev] and w["evidence"][ev]["expires_at"] == s["evidence_expires_at"]
    assert ev not in o.valid_evidence()
    # the approved path exists but is invalid; the other path is a proposal only
    paths = o.explain(req)["paths"]
    assert [(p["control"], p["evidence"], p["valid"]) for p in paths] == [(ctrl, ev, False)]
    assert o.proposed_only(req) == [s["proposal_only_control"]]
    assert w["proposals"][s["proposal"]]["status"] == "pending"
    assert s["proposal_only_control"] not in {m["control"] for ms in w["maps"].values() for m in ms
                                               if m["requirement"] == req}
    row = next(r for r in w["legacy"] if r["control_id"] == ctrl)
    assert s["legacy_tracker_status_contains"] in row["status"]
    assert sorted(a for a, v in w["audits"].items() if ev in v["requests"]) == s["expected"]["audits_requesting_evidence"]
    assert [x["control"] for x in o.legacy_stale()] == s["expected"]["legacy_stale_controls"]


def test_s2_expiring_before_audit(w):
    s = P["S2"]
    e = s["expected"]
    b = o.blast(until=s["audit_date"])
    assert [x["evidence"] for x in b["expiring_evidence"]] == e["expiring_until_audit_171"] == s["evidence"]
    for ev, ctrl in s["controls"].items():
        assert w["proves"][ctrl] == [ev]  # each is the only evidence for its control
        assert w["evidence"][ev]["expires_at"] == s["expires_at"][ev]
    assert b["controls_left_without_valid_evidence"] == e["controls_left_without_evidence"]
    assert len(b["broken_by_framework"]["800-171"]) == e["broken_800_171_count"] == 9
    assert b["broken_by_framework"]["800-171"] == e["broken_800_171"]
    assert b["broken_by_framework"]["800-53"] == e["broken_800_53_until_audit_171"]
    assert b["broken_by_framework"]["CSF"] == []
    still = [x["requirement"] for x in b["broken_requirements"] if x["framework"] == "800-171" and x["still_inherited"]]
    assert still == e["still_inherited"]
    assert [x["requirement"] for x in b["broken_requirements"]
            if x["framework"] == "800-171" and not x["still_inherited"]] == e["broken_and_not_inherited"]
    assert [a["audit"] for a in b["affected_audits"]] == e["affected_audits_until_audit_171"]
    # 800-53 broken requirements are never "inherited"
    assert not any(x["still_inherited"] for x in b["broken_requirements"] if x["framework"] == "800-53")
    # 30-day window
    b30 = o.blast(30)
    assert [x["evidence"] for x in b30["expiring_evidence"]] == e["expiring_within_30_days"]
    assert len(b30["broken_by_framework"]["800-171"]) == e["broken_800_171_within_30_days_count"]
    assert b30["broken_by_framework"]["800-53"] == e["broken_800_53_within_30_days"]
    assert [a["audit"] for a in b30["affected_audits"]] == e["affected_audits_within_30_days"]
    # exactly these 3 evidence items expire between as_of and the audit date
    between = [i for i, ev in w["evidence"].items()
               if w["as_of"] < o._d(ev["expires_at"]) <= o._d(s["audit_date"])]
    assert sorted(between) == s["evidence"]


def test_s3_single_owner(w):
    e = P["S3"]["expected"]
    r = o.q6_owner_risk()
    d = r["people"][P["S3"]["person"]]
    assert d["controls_solely_owned"] == sorted(e["sole_owned_controls"], key=o._nk)
    assert d["sole_owned_count"] == e["sole_owned_count"] == 6
    assert len(d["controls_touching_high_systems"]) == e["controls_touching_high_criticality_systems"] == 6
    assert {"person": P["S3"]["person"], "sole_owned_count": 6, "controls_touching_high_systems": 6} in r["sole_owner_ranking"]
    # Dana owns nothing else (not even as a co-owner)
    owned = [c for c, v in w["controls"].items() if P["S3"]["person"] in (v["owners"] or [])]
    assert sorted(owned) == sorted(e["sole_owned_controls"])


def test_s4_rejected_suggestion(w):
    s, e = P["S4"], P["S4"]["expected"]
    d = w["decisions"][s["decision"]]
    assert (d["control"], d["requirement"], d["decision"]) == (s["control"], s["requirement"], "rejected")
    assert d["decided_by"] == s["decided_by"] and str(d["decided_at"]) == s["decided_at"]
    assert d["reason"] == s["reason"]
    assert w["proposals"][s["proposal"]]["status"] == "rejected"
    assert s["control"] in w["controls"]
    assert (s["new_control"] in w["library"]) is e["new_control_in_library"]
    assert (s["new_control"] in w["controls"]) is e["new_control_adopted"]
    assert any(r["control"] == s["control"] and r["requirement"] == s["requirement"] for r in o.rejections())
    other = e["other_rejection"]
    assert any(r["control"] == other["control"] and r["requirement"] == other["requirement"]
               and r["decided_at"] == other["decided_at"] for r in o.rejections())
    # the rejected mapping was never approved
    assert not any(m["requirement"] == s["requirement"] for m in w["maps"][s["control"]])


def test_s5_inherited_coverage(w):
    e = P["S5"]["expected"]
    cov = o.q1_coverage()["by_framework"]
    c171, ccsf = cov["800-171"], cov["CSF"]
    assert c171["counts"] == {"direct": e["direct_171"], "inherited": e["inherited_171_at_1_hop"], "gap": e["gap_171"]}
    assert c171["inherited"] == e["inherited_171"]
    assert ccsf["counts"] == {"direct": e["csf_direct"], "inherited": e["csf_inherited"], "gap": e["csf_gap"]}
    # inherited requirements have no direct mapping at all in the pack
    mapped = {m["requirement"] for ms in w["maps"].values() for m in ms}
    assert not set(c171["inherited"]) & mapped
    assert not any(r.startswith("CSF:") for r in mapped)
    # every inherited requirement lists the neighbour(s) and control(s) giving it
    for item in o.q2_adopt("800-171")["inherited"]:
        assert item["via"] and all(v["controls"] for v in item["via"])
    assert o.q2_adopt("CSF")["inherited_count"] == e["csf_inherited"]
    assert o.q2_adopt("800-53")["inherited_count"] == 0


def test_s6_decoy(w):
    s, e = P["S6"], P["S6"]["expected"]
    ce = o.control_evidence()
    assert o._d(w["evidence"][s["expired_evidence"]]["expires_at"]).isoformat() == s["expired_at"]
    assert s["expired_evidence"] not in o.valid_evidence()
    assert ce[s["control"]] == sorted(s["replacements"])
    b30, b171 = o.blast(30), o.blast(until="2027-01-15")
    for b, key in ((b30, "flagged_by_blast_30d"), (b171, "flagged_by_blast_until_audit_171")):
        flagged = (s["expired_evidence"] in [x["evidence"] for x in b["expiring_evidence"]]
                   or s["requirement"] in [x["requirement"] for x in b["broken_requirements"]]
                   or s["control"] in b["controls_left_without_valid_evidence"])
        assert flagged is e[key]
    assert (s["requirement"] in o.direct_coverage()) is e["requirement_covered_direct"]
    assert any(d["evidence"] == s["expired_evidence"] and d["control"] == s["control"] for d in o.decoys())
    assert (s["control"] in b30["controls_left_without_valid_evidence"]) is e["control_left_without_evidence"]


def test_s7_duplicate_evidence(w):
    s, e = P["S7"], P["S7"]["expected"]
    rank = o.q4_reuse()
    top = rank[0]
    assert top["evidence"] == s["evidence"] and top["rank"] == e["reuse_rank"] == 1
    assert top["controls"] == sorted(s["controls"], key=o._nk)
    assert top["direct_count"] == e["direct_requirements"]
    assert top["frameworks_direct"] == e["frameworks_direct"]
    assert top["frameworks_reached"] == e["frameworks_reached"]
    assert top["reach_count"] == e["reach_count_1_hop"]
    assert sorted(a for a, v in w["audits"].items() if s["evidence"] in v["requests"]) == e["requested_by"]
    nxt = rank[1]
    assert (nxt["evidence"], nxt["direct_count"]) == (e["next_best"]["evidence"], e["next_best"]["direct_requirements"])
    # only valid evidence is ranked
    assert {r["evidence"] for r in rank} == o.valid_evidence()


def test_s8_unowned_control(w):
    s, e = P["S8"], P["S8"]["expected"]
    assert o.q6_owner_risk()["unowned_controls"] == e["unowned_controls"] == [s["control"]]
    assert w["controls"][s["control"]]["owners"] == []
    assert w["controls"][s["control"]]["status"] == e["status"]
    assert (s["control"] in o.control_evidence()) is e["has_valid_evidence"]
    row = next(r for r in w["legacy"] if r["control_id"] == s["control"])
    assert row["owner"] == e["legacy_owner_name"]
    assert (row["owner"] in {p["name"] for p in w["people"].values()}) is e["legacy_owner_in_people"]
