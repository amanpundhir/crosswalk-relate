"""Oracle determinism, ground_truth.json freshness, and eval file sanity."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"crosswalk_{name}", EVAL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


o = _load("oracle")
G = _load("build_golden")


def test_render_is_deterministic():
    assert o.render() == o.render()
    a, b = json.loads(o.render()), json.loads(o.render())
    assert a == b


def test_ground_truth_up_to_date():
    committed = (EVAL / "ground_truth.json").read_bytes()
    assert committed == o.render().encode("utf-8"), "run: python -I eval/oracle.py"
    assert b"\r\n" not in committed


def test_cli_reproduces_ground_truth_byte_for_byte(tmp_path):
    before = (EVAL / "ground_truth.json").read_bytes()
    subprocess.run([sys.executable, "-I", str(EVAL / "oracle.py")], check=True, capture_output=True, cwd=tmp_path)
    assert (EVAL / "ground_truth.json").read_bytes() == before


def test_ground_truth_headline_shape():
    gt = json.loads((EVAL / "ground_truth.json").read_text(encoding="utf-8"))
    assert gt["as_of"] == "2026-12-02"
    fw = gt["q1_coverage"]["by_framework"]
    assert fw["800-171"]["active_requirements"] == 97
    assert fw["CSF"]["active_requirements"] == 106
    assert fw["800-53"]["active_requirements"] == 1014
    for c in fw.values():  # direct, inherited and gap partition the framework
        n = c["counts"]
        assert n["direct"] + n["inherited"] + n["gap"] == c["active_requirements"]
        assert not set(c["covered_direct"]) & set(c["inherited"])
    assert fw["800-53"]["counts"]["inherited"] == 0
    assert set(gt["q3_blast_until_audit"]) == {"AUD-171", "AUD-53", "AUD-CSF"}


def test_coverage_is_never_inherited_for_800_53_and_respects_one_hop():
    w = o.world()
    cov = o.direct_coverage()
    for r in o.inherited_set("800-171", cov):
        assert r not in cov
        assert any(n in cov for n in w["adj"][r])  # a 1-hop neighbour is covered directly


def test_golden_questions_up_to_date_and_well_formed():
    assert (EVAL / "golden_questions.yaml").read_text(encoding="utf-8") == G.render()
    qs = yaml.safe_load((EVAL / "golden_questions.yaml").read_text(encoding="utf-8"))
    assert len(qs) == 20 and len({q["id"] for q in qs}) == 20
    traps = {q["trap"] for q in qs if q["trap"]}
    assert {"S1", "S2", "S4", "S5", "S6", "S8"} <= traps
    assert sum(1 for q in qs if q["trap"]) >= 6
    w = o.world()
    known = (set(w["reqs"]) | set(w["controls"]) | set(w["evidence"]) | set(w["people"]) | set(w["audits"])
             | set(w["proposals"]) | set(w["decisions"]) | set(o.FRAMEWORKS))
    for q in qs:
        assert set(q) == {"id", "question", "expected", "must_cite", "trap"}
        assert q["expected"] and q["question"].endswith(("?", "."))
        assert set(q["must_cite"]) <= known, (q["id"], set(q["must_cite"]) - known)


def test_bad_proposals_use_real_ids_and_cover_all_kinds():
    w = o.world()
    bad = yaml.safe_load((EVAL / "bad_proposals.yaml").read_text(encoding="utf-8"))
    assert len(bad) == 8 and len({b["id"] for b in bad}) == 8
    assert {b["expected_reason"] for b in bad} == {
        "duplicate", "nonexistent_target", "withdrawn_target", "previously_rejected", "wrong_framework",
        "evidence_not_expiring", "unknown_person", "contradictory_status"}
    by = {b["expected_reason"]: b for b in bad}
    from crosswalk.sources import nist
    withdrawn = set().union(*(x[2] for x in nist._load_all(nist.DEFAULT_RAW_DIR).values()))
    for b in bad:
        p = b["proposal"]
        if "control" in p:
            assert p["control"] in w["controls"]
    d = by["duplicate"]["proposal"]
    assert any(m["requirement"] == d["requirement"] for m in w["maps"][d["control"]])
    assert by["nonexistent_target"]["proposal"]["requirement"] not in set(w["reqs"]) | withdrawn
    assert by["withdrawn_target"]["proposal"]["requirement"] in withdrawn
    r = by["previously_rejected"]["proposal"]
    assert any(x["control"] == r["control"] and x["requirement"] == r["requirement"] for x in o.rejections())
    f = by["wrong_framework"]["proposal"]
    assert f["requirement"] in w["reqs"] and o.fw_of(f["requirement"]) != f["target_framework"]
    ev = w["evidence"][by["evidence_not_expiring"]["proposal"]["evidence"]]
    assert (o._d(ev["expires_at"]) - w["as_of"]).days > 90
    assert by["unknown_person"]["proposal"]["owner"] not in w["people"]
    c = by["contradictory_status"]["proposal"]
    assert c["status"] == "approved" and c["decided_by"] is None and c["decision"] is None
