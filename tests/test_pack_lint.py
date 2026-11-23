"""Pack lint: every id referenced in inputs/company/ exists and is well formed."""
import csv
import datetime as dt
import json
import re
from pathlib import Path

import yaml

from crosswalk.sources import comply

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "inputs" / "company"
RAW = ROOT / "inputs" / "nist" / "raw"
AS_OF = dt.date(2026, 12, 2)


def load(name):
    return yaml.safe_load((PACK / name).read_text(encoding="utf-8"))


def d(v):
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(v)


def _withdrawn(c):
    return any(p.get("name") == "status" and p.get("value") == "withdrawn" for p in c.get("props", []))


def active_requirements():
    ids = set()
    cat = json.loads((RAW / "NIST_SP-800-53_rev5_catalog.json").read_text(encoding="utf-8"))["catalog"]

    def walk(c):
        if not _withdrawn(c):
            ids.add("800-53:" + re.sub(r"\.(\d+)$", r"(\1)", c["id"].upper()))
        for s in c.get("controls", []):
            walk(s)

    for g in cat["groups"]:
        for c in g.get("controls", []):
            walk(c)
    cat = json.loads((RAW / "NIST_SP800-171_rev3_catalog.json").read_text(encoding="utf-8"))["catalog"]
    for g in cat["groups"]:
        for c in g.get("controls", []):
            if not _withdrawn(c):
                ids.add("800-171:" + c["id"].replace("SP_800_171_", ""))
    return ids


def dup_free(rows, key="id"):
    keys = [r[key] for r in rows]
    assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]


PEOPLE = load("people.yaml")
SYSTEMS = load("systems.yaml")
CONTROLS = load("controls.yaml")
EVIDENCE = load("evidence.yaml")
AUDITS = load("audits.yaml")
MAPPINGS = load("mappings.yaml")
PROPOSALS = load("proposals.yaml")
DECISIONS = load("decisions.yaml")
COMPANY = load("company.yaml")
PIDS = {p["id"] for p in PEOPLE}
SIDS = {s["id"] for s in SYSTEMS}
CIDS = {c["id"] for c in CONTROLS}
EIDS = {e["id"] for e in EVIDENCE}
LIB = {c["id"]: c for c in comply.load_controls(ROOT / "inputs" / "templates" / "comply")}
REQS = active_requirements()
DANA = "P-dana-okafor"


def test_sizes():
    assert len(PEOPLE) == 15 and len(SYSTEMS) == 25 and len(CONTROLS) == 61
    assert len(EVIDENCE) == 120 and len(AUDITS) == 3
    assert 120 <= len(MAPPINGS) <= 180
    assert 6 <= len(PROPOSALS) <= 10 and 3 <= len(DECISIONS) <= 6


def test_as_of_and_disclaimer():
    assert str(COMPANY["as_of"]) == "2026-12-02"
    assert "fictional" in COMPANY["name"].lower() and "fictional" in COMPANY["disclaimer"].lower()


def test_no_duplicate_ids():
    for rows in (PEOPLE, SYSTEMS, CONTROLS, EVIDENCE, AUDITS, PROPOSALS, DECISIONS):
        dup_free(rows)
    pairs = [(m["control"], m["requirement"]) for m in MAPPINGS]
    assert len(pairs) == len(set(pairs))


def test_id_formats():
    assert all(re.fullmatch(r"P-[a-z0-9-]+", i) for i in PIDS)
    assert all(re.fullmatch(r"SYS-[a-z0-9-]+", i) for i in SIDS)
    assert all(re.fullmatch(r"EV-\d{3}", i) for i in EIDS)
    assert {s["criticality"] for s in SYSTEMS} <= {"high", "med", "low"}
    assert {e["kind"] for e in EVIDENCE} <= {"screenshot", "config-export", "report", "ticket", "attestation"}
    assert {c["status"] for c in CONTROLS} <= {"implemented", "partial", "planned"}


def test_required_people():
    names = {p["name"]: p for p in PEOPLE}
    assert names["Maya Chen"]["role"].lower().startswith("security lead")
    assert names["Dana Okafor"]["role"].lower() == "it admin"


def test_controls_are_in_library_and_not_vague():
    for c in CONTROLS:
        assert c["id"] in LIB, c["id"]
        assert LIB[c["id"]]["vague"] is False, c["id"]
        assert set(c["owners"]) <= PIDS
        assert set(c["applies_to"]) <= SIDS and c["applies_to"]
    assert len({LIB[c["id"]]["policy"] for c in CONTROLS}) >= 12


def test_evidence_references_and_dates():
    for e in EVIDENCE:
        assert set(e["proves"]) <= CIDS and e["proves"], e["id"]
        assert e["owner"] in PIDS
        c, x = d(e["collected_at"]), d(e["expires_at"])
        assert dt.date(2026, 1, 1) <= c <= dt.date(2026, 11, 30), e["id"]
        assert x > c
        assert e["location"]


def test_audits():
    by = {a["id"]: a for a in AUDITS}
    assert d(by["AUD-171"]["date"]) == dt.date(2027, 1, 15)
    assert d(by["AUD-53"]["date"]) == dt.date(2027, 2, 20)
    assert d(by["AUD-CSF"]["date"]) == dt.date(2027, 3, 31)
    for a in AUDITS:
        assert set(a["requests"]) <= EIDS
        assert len(a["requests"]) == len(set(a["requests"]))
        assert a["scope"]["framework"] == a["framework"]
        assert set(a["scope"]) <= {"framework", "baseline"}
    assert by["AUD-53"]["scope"]["baseline"] == "MODERATE"
    assert "baseline" not in by["AUD-171"]["scope"] and "baseline" not in by["AUD-CSF"]["scope"]


def test_mappings_reference_real_active_requirements():
    for m in MAPPINGS:
        assert m["control"] in CIDS, m
        assert m["requirement"] in REQS, m
        assert not m["requirement"].startswith("CSF:"), "no direct CSF mappings allowed"
        assert m["approved_by"] in PIDS
        assert d(m["approved_at"]) <= AS_OF
    n53 = sum(m["requirement"].startswith("800-53:") for m in MAPPINGS)
    n171 = sum(m["requirement"].startswith("800-171:") for m in MAPPINGS)
    assert n53 > n171 > 0


def test_proposals_and_decisions():
    pids = {p["id"] for p in PROPOSALS}
    for p in PROPOSALS:
        assert p["control"] in CIDS or p["control"] in LIB
        assert p["requirement"] in REQS
        assert p["by"] and p["rationale"] and d(p["created_at"]) <= AS_OF
        assert p["status"] in ("pending", "approved", "rejected")
    for x in DECISIONS:
        assert x["proposal"] in pids and x["decided_by"] in PIDS and d(x["decided_at"]) <= AS_OF
        assert x["decision"] in ("approved", "rejected") and x["reason"]
    mapped = {(m["control"], m["requirement"]) for m in MAPPINGS}
    for x in DECISIONS:
        key = (x["control"], x["requirement"])
        assert (key in mapped) == (x["decision"] == "approved"), x
    for p in PROPOSALS:
        if p["status"] in ("pending", "rejected"):
            assert (p["control"], p["requirement"]) not in mapped


def test_legacy_tracker():
    with (PACK / "legacy_tracker.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert 55 <= len(rows) <= 65
    assert list(rows[0]) == ["control_id", "requirement_ids", "owner", "status", "last_reviewed"]
    for r in rows:
        assert r["control_id"] in CIDS
        for q in r["requirement_ids"].split(";"):
            assert q in REQS, q
        d(r["last_reviewed"])


def test_s3_dana_sole_owner_of_six_high_criticality_controls():
    high = {s["id"] for s in SYSTEMS if s["criticality"] == "high"}
    owned = [c for c in CONTROLS if DANA in c["owners"]]
    assert len(owned) == 6
    assert all(c["owners"] == [DANA] for c in owned)
    assert all(set(c["applies_to"]) & high for c in owned)


def test_s8_unowned_control():
    unowned = [c["id"] for c in CONTROLS if not c["owners"]]
    assert unowned == ["CTRL-MCP-13"]


def test_s1_s2_evidence_facts():
    ev = {e["id"]: e for e in EVIDENCE}
    assert ev["EV-044"]["proves"] == ["CTRL-REAP-6"] and ev["EV-044"]["expires_at"] == "2026-12-01"
    assert [e["id"] for e in EVIDENCE if "CTRL-REAP-6" in e["proves"]] == ["EV-044"]
    window = [e for e in EVIDENCE if AS_OF < d(e["expires_at"]) <= dt.date(2027, 1, 15)]
    assert {e["id"] for e in window} == {"EV-100", "EV-101", "EV-102"}
