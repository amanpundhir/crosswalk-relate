"""Tests for crosswalk.sources.nist (reads inputs/nist/raw; no Relate)."""

from __future__ import annotations

import re

import pytest

from crosswalk.sources import nist

RAW = nist.DEFAULT_RAW_DIR


@pytest.fixture(scope="module")
def reqs() -> list[dict]:
    return nist.load_requirements(RAW)


@pytest.fixture(scope="module")
def by_id(reqs: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in reqs}


@pytest.fixture(scope="module")
def crosswalk() -> tuple[list[dict], list[str]]:
    return nist.load_crosswalk(RAW)


def _fw(reqs: list[dict], fw: str) -> list[dict]:
    return [r for r in reqs if r["framework"] == fw]


# ---- counts ---------------------------------------------------------------


def test_800_53_counts(reqs):
    r53 = _fw(reqs, "800-53")
    assert sum(not r["is_enhancement"] for r in r53) == 300
    assert sum(r["is_enhancement"] for r in r53) == 714


def test_800_171_count(reqs):
    assert len(_fw(reqs, "800-171")) == 97


def test_csf_count(reqs):
    assert len(_fw(reqs, "CSF")) == 106


def test_family_counts():
    fams = nist.load_families(RAW)
    count = {fw: sum(f["framework"] == fw for f in fams) for fw in ("800-53", "800-171", "CSF")}
    assert count == {"800-53": 20, "800-171": 17, "CSF": 22}


def test_frameworks():
    assert [f["id"] for f in nist.load_frameworks()] == ["800-53", "800-171", "CSF"]
    assert all(f["name"] and f["version"] for f in nist.load_frameworks())


# ---- id formats -----------------------------------------------------------

ID_RE = {
    "800-53": re.compile(r"800-53:[A-Z]{2}-[1-9]\d*(\([1-9]\d*\))?"),
    "800-171": re.compile(r"800-171:03\.\d\d\.\d\d"),
    "CSF": re.compile(r"CSF:(GV|ID|PR|DE|RS|RC)\.[A-Z]{2}-\d\d"),
}
FAMILY_RE = {
    "800-53": re.compile(r"800-53:[A-Z]{2}"),
    "800-171": re.compile(r"800-171:03\.\d\d"),
    "CSF": re.compile(r"CSF:(GV|ID|PR|DE|RS|RC)\.[A-Z]{2}"),
}


def test_id_formats(reqs):
    for r in reqs:
        assert ID_RE[r["framework"]].fullmatch(r["id"]), r["id"]
        assert FAMILY_RE[r["framework"]].fullmatch(r["family_id"]), r["family_id"]


def test_ids_unique(reqs):
    assert len({r["id"] for r in reqs}) == len(reqs)


def test_family_ids_exist(reqs):
    fam_ids = {f["id"] for f in nist.load_families(RAW)}
    assert {r["family_id"] for r in reqs} <= fam_ids


def test_required_fields(reqs):
    for r in reqs:
        for key in ("id", "framework", "family_id", "family_title", "title", "text"):
            assert isinstance(r[key], str) and r[key].strip(), (r["id"], key)


def test_enhancement_parents(reqs, by_id):
    for r in _fw(reqs, "800-53"):
        if r["is_enhancement"]:
            assert r["id"].startswith(r["parent_id"] + "(")
            assert r["parent_id"] in by_id
        else:
            assert r["parent_id"] is None


# ---- known items ----------------------------------------------------------


def test_known_items(by_id):
    assert by_id["800-171:03.01.01"]["title"] == "Account Management"
    assert by_id["800-53:AC-2"]["title"] == "Account Management"
    assert by_id["800-53:IA-2(1)"]["is_enhancement"]
    assert by_id["800-53:IA-2(1)"]["parent_id"] == "800-53:IA-2"
    assert "CSF:PR.AA-01" in by_id
    assert by_id["800-53:AC-2"]["family_title"] == "Access Control"


def test_no_withdrawn(by_id):
    # ac-2.10 (withdrawn enhancement), 03.01.13 (withdrawn 171), PR.AC-01 (CSF 1.1 stub)
    for gone in ("800-53:AC-2(10)", "800-171:03.01.13", "CSF:PR.AC-01", "800-53:RA-4"):
        assert gone not in by_id


# ---- text -----------------------------------------------------------------


def test_placeholders_resolved(reqs):
    for r in reqs:
        assert "{{" not in r["text"] and "}}" not in r["text"], r["id"]
        assert "insert:" not in r["text"], r["id"]


def test_placeholder_rendering(by_id):
    assert "[organization-defined prerequisites and criteria]" in by_id["800-53:AC-2"]["text"]
    # selection with a nested placeholder inside a choice
    assert "[Selection (one or more):" in by_id["800-171:03.01.08"]["text"]
    assert "lock the account or node for an [organization-defined" in by_id["800-171:03.01.08"]["text"]
    # params defined on a sibling control still resolve
    assert "[organization-defined" in by_id["800-53:IA-13(3)"]["text"]


# ---- crosswalk ------------------------------------------------------------


def test_crosswalk_endpoints_exist(crosswalk, by_id):
    edges, _ = crosswalk
    assert edges
    for e in edges:
        assert e["a"] in by_id and e["b"] in by_id, e


def test_crosswalk_kinds_and_sources(crosswalk, by_id):
    edges, _ = crosswalk
    for e in edges:
        a, b = by_id[e["a"]], by_id[e["b"]]
        if e["kind"] == "derived-from":
            assert (a["framework"], b["framework"]) == ("800-171", "800-53")
            assert e["source"] in {"overlay", "oscal", "both"}
        else:
            assert e["kind"] == "informative-reference"
            assert e["source"] == "csf2.xlsx"
            assert a["framework"] == "CSF" and b["framework"] in {"800-53", "800-171"}


def test_crosswalk_counts(crosswalk, by_id):
    edges, _ = crosswalk
    csf53 = [e for e in edges if e["kind"] == "informative-reference" and e["b"].startswith("800-53")]
    csf171 = [e for e in edges if e["kind"] == "informative-reference" and e["b"].startswith("800-171")]
    derived = [e for e in edges if e["kind"] == "derived-from"]
    assert len(csf53) == 736  # 740 lines minus 3 family codes and 1 withdrawn target
    assert len(csf171) == 310
    assert len(derived) == 158  # 153 both + 4 oscal-only + 1 overlay-only
    assert {r for r in (e["b"] for e in derived)} <= {i for i in by_id}
    assert sum(e["source"] == "both" for e in derived) == 153


def test_crosswalk_no_duplicates(crosswalk):
    edges, _ = crosswalk
    keys = [(frozenset((e["a"], e["b"])), e["kind"]) for e in edges]
    assert len(keys) == len(set(keys))


def test_crosswalk_normalised_53_ids(crosswalk):
    edges, _ = crosswalk
    assert any(e["b"] == "800-53:AC-2(3)" or e["b"] == "800-53:AC-2" for e in edges)
    for e in edges:
        assert not re.search(r"-0\d|\(0\d\)", e["b"]), e


def test_warnings(crosswalk):
    _, warns = crosswalk
    kinds = {w.split(":")[0] for w in warns}
    assert kinds == {"family-code", "withdrawn-target", "unknown-target"}
    assert sum(w.startswith("family-code") for w in warns) == 3
    assert any("800-53:RA-4" in w and w.startswith("withdrawn-target") for w in warns)


def test_norm_53():
    assert nist.norm_53("AC-02(03)") == "AC-2(3)"
    assert nist.norm_53("ac-2.13") == "AC-2(13)"
    assert nist.norm_53("PM-11") == "PM-11"
    assert nist.norm_53("PT") is None
    assert nist.norm_53("junk") is None


# ---- determinism ----------------------------------------------------------


def test_determinism_and_sorting(reqs, crosswalk):
    assert nist.load_requirements(RAW) == reqs
    assert nist.load_crosswalk(RAW) == crosswalk
    assert nist.load_families(RAW) == nist.load_families(RAW)
    order = {"800-53": 0, "800-171": 1, "CSF": 2}
    keyed = [(order[r["framework"]], nist.natural_key(r["id"])) for r in reqs]
    assert keyed == sorted(keyed)
    edges, warns = crosswalk
    ekeys = [(e["kind"], nist.natural_key(e["a"]), nist.natural_key(e["b"])) for e in edges]
    assert ekeys == sorted(ekeys)
    assert warns == sorted(warns)


def test_moderate_baseline(by_id):
    base = nist.load_baseline(RAW, "MODERATE")
    assert len(base) == 287
    assert "800-53:AC-2" in base and "800-53:AC-2(1)" in base
    assert base <= {i for i, r in by_id.items() if r["framework"] == "800-53"}
    with pytest.raises(ValueError):
        nist.load_baseline(RAW, "NOPE")
