"""Tests for crosswalk.build and crosswalk.coverage (build a throwaway store in tmp)."""

from __future__ import annotations

import json

import pytest
import relate

from crosswalk import build as B
from crosswalk import coverage as C
from crosswalk.sources import nist


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("store")
    store = d / "crosswalk"
    res = B.build(store, export=False)
    return store, res


@pytest.fixture(scope="module")
def conn(built):
    store, _ = built
    c = relate.connect(str(store), read_only=True)
    yield c
    c.close()


def test_node_counts_match_loaders(built):
    _, res = built
    s = B.load_sources()
    nodes, _ = B._expected_counts(s)
    assert res.nodes == dict(sorted(nodes.items()))
    assert res.nodes["Requirement"] == len(s.requirements)


def test_edge_counts_match_loaders(built):
    _, res = built
    _, rels = B._expected_counts(B.load_sources())
    assert res.relationships == dict(sorted(rels.items()))


def test_clean_close(built):
    store, _ = built
    B.check_clean_close(store)


def test_json_codec_on_disk(built):
    store, _ = built
    assert B.read_manifest(store)["codec"] == "json"
    assert json.loads((store / "graph.json").read_text(encoding="utf-8"))


def test_indexes_exist(conn):
    names = {r["name"] for r in conn.execute("SHOW INDEXES").fetchall()}
    for name, _label, _prop in B.RANGE_INDEXES:
        assert name in names


def test_dates_and_meta(conn):
    rows = conn.execute("MATCH (m:Meta) RETURN toString(m.as_of) AS a, m.company AS c").fetchall()
    assert len(rows) == 1 and rows[0]["a"] == str(B.load_sources().company["as_of"])
    a = conn.execute("MATCH (a:Audit {id: 'AUD-53'}) RETURN toString(a.date) AS d, a.scope_baseline AS b").fetchall()
    assert a[0]["d"] == "2027-02-20" and a[0]["b"] == "MODERATE"


def test_baseline_property(conn):
    n = conn.execute("MATCH (r:Requirement) WHERE 'MODERATE' IN r.baselines RETURN count(r) AS n").fetchall()[0]["n"]
    assert n == len(nist.load_baseline(nist.DEFAULT_RAW_DIR, "MODERATE")) == 287


def test_deterministic(tmp_path):
    a = B.build(tmp_path / "a", export=False).store_dir
    b = B.build(tmp_path / "b", export=False).store_dir
    assert (a / "graph.json").read_bytes() == (b / "graph.json").read_bytes()


def test_coverage_every_171_requirement_has_status(conn):
    res = C.coverage(conn, "800-171")
    assert res["total"] == 97 == len(res["requirements"])
    assert {r["status"] for r in res["requirements"]} <= {"covered", "inherited", "gap"}
    assert res["covered"] + res["inherited"] + res["gaps"] == 97


def test_coverage_honours_as_of(conn):
    # a day before EV-044 expires its control counts as having valid evidence
    early = C.coverage(conn, "800-171", "2026-11-30")
    late = C.coverage(conn, "800-171", "2026-12-02")
    assert early["covered"] >= late["covered"]
    assert by_status(early, "800-171:03.05.03") == "covered"
    assert by_status(late, "800-171:03.05.03") != "covered"


def by_status(res, rid):
    return next(r["status"] for r in res["requirements"] if r["id"] == rid)


def test_coverage_other_frameworks(conn):
    csf = C.coverage(conn, "CSF")
    assert csf["total"] == 106 and csf["covered"] == 0  # no mappings go to CSF
    assert csf["inherited"] > 0
    f53 = C.coverage(conn, "800-53")
    assert f53["total"] == 1014 and f53["inherited"] == 0


def test_coverage_audit_scope(conn):
    res = C.coverage(conn, audit="AUD-53")
    assert res["framework"] == "800-53" and res["baseline"] == "MODERATE"
    assert res["total"] == 287 == len(res["requirements"])
    assert res["covered"] + res["gaps"] == 287
    full = C.coverage(conn, "800-53")
    assert 0 < res["covered"] <= full["covered"]
    assert C.coverage(conn, audit="AUD-171")["total"] == 97
