"""Tests for the deterministic control splitter (spec section 2)."""
import json
import re
from pathlib import Path

from crosswalk.sources import comply

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "inputs" / "templates" / "comply"


def lib():
    return comply.load_controls(TEMPLATES)


def by_id():
    return {c["id"]: c for c in lib()}


def test_at_least_400_controls():
    assert len(lib()) >= 400


def test_deterministic_ids_and_hashes():
    a, b = lib(), lib()
    assert [(c["id"], c["text_sha"]) for c in a] == [(c["id"], c["text_sha"]) for c in b]


def test_ids_unique_sequential_per_policy():
    seen = {}
    for c in lib():
        m = re.fullmatch(r"CTRL-([A-Z]+)-(\d+)", c["id"])
        assert m and m.group(1) == c["policy"]
        n = int(m.group(2))
        assert n == seen.get(c["policy"], 0) + 1, c["id"]
        seen[c["policy"]] = n
    assert len(seen) == 25  # 27 policies minus the two stubs


def test_fields_and_hash_format():
    for c in lib():
        assert {"id", "policy", "title", "text", "text_sha", "vague"} <= set(c)
        assert re.fullmatch(r"[0-9a-f]{12}", c["text_sha"])
        assert isinstance(c["vague"], bool)
        assert c["text"] and len(c["title"]) <= 84
        assert "**" not in c["text"] and not c["text"].startswith("*")


def test_spot_check_known_ids():
    L = by_id()
    assert L["CTRL-PWP-1"]["text"].startswith(
        "All system-level passwords should be rotated on at least a quarterly basis")
    assert L["CTRL-AP-8"]["text"] == "Full backups of critical resources are performed on at least a weekly basis."
    assert "rotate keys at least once every 12 months" in L["CTRL-EP-8"]["text"]
    assert "multi-factor authentication" in L["CTRL-REAP-6"]["text"]
    assert L["CTRL-AOTP-11"]["text"] == "Each month, IT and HR will review accounts and permission levels for accuracy."
    assert L["CTRL-PWP-1"]["text_sha"] == "206fe70c4565"


def test_skipped_sections_and_stubs_yield_nothing():
    L = lib()
    assert not any(c["policy"] in ("PMP", "PIP") for c in L)
    assert not any(
        re.search(r"is to define expected behavior|describes the procedure to select", c["text"]) for c in L)


def test_level3_children_are_folded():
    t = by_id()["CTRL-COCP-3"]["text"]
    assert " | " in t and t.startswith("Company property")


def test_vague_flag():
    L = lib()
    assert by_id()["CTRL-PWP-1"]["vague"] is False
    assert 40 <= sum(c["vague"] for c in L) <= 160
    assert any(c["vague"] and len(c["text"].split()) < 8 for c in L)


def test_dump_roundtrip(tmp_path):
    out = tmp_path / "lib.json"
    controls = comply.dump(TEMPLATES, out)
    assert json.loads(out.read_text(encoding="utf-8")) == controls
