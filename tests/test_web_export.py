"""The browser export (``python -m crosswalk.export_web``) is deterministic, small, and rebuilds the same graph."""
import json
from pathlib import Path

import pytest
import relate

from crosswalk import export_web
from crosswalk.build import DEFAULT_STORE, QUERIES_DIR, count_graph

ROOT = Path(__file__).resolve().parents[1]
MAX_GRAPH_BYTES = 1_500_000  # a few hundred KB gzipped; keep the page light


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("web")
    meta = export_web.export_web(DEFAULT_STORE, out)
    return out, meta


@pytest.fixture(scope="module")
def store():
    conn = relate.connect(str(DEFAULT_STORE), read_only=True)
    yield conn
    conn.close()


def _statements(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.rstrip(";") for ln in lines if ln.strip() and not ln.startswith("//")]


def test_export_is_deterministic(exported, tmp_path):
    out, _ = exported
    again = tmp_path / "again"
    export_web.export_web(DEFAULT_STORE, again)
    for rel in ("data/graph.cypher", "data/meta.json"):
        assert (out / rel).read_bytes() == (again / rel).read_bytes(), rel


def test_graph_cypher_is_small_and_has_no_embeddings(exported):
    out, meta = exported
    text = (out / "data" / "graph.cypher").read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) < MAX_GRAPH_BYTES
    assert "embedding:" not in text
    assert "text_sha" not in text
    assert meta["statements"] == len(_statements(out / "data" / "graph.cypher"))


def test_graph_cypher_rebuilds_the_store_in_memory(exported, store):
    """Every statement runs in a fresh in-memory Relate; counts and the headline numbers equal the store's."""
    out, meta = exported
    mem = relate.connect(":memory:")
    try:
        for stmt in _statements(out / "data" / "graph.cypher"):
            mem.execute(stmt)
        want_nodes, want_rels = count_graph(store)
        got_nodes, got_rels = count_graph(mem)
        assert got_nodes == want_nodes
        assert got_rels == want_rels
        assert sum(got_nodes.values()) == meta["total_nodes"] == sum(want_nodes.values())
        assert sum(got_rels.values()) == meta["total_relationships"]

        q1 = (QUERIES_DIR / "q1_coverage.cypher").read_text(encoding="utf-8")
        params = {"framework": "800-171", "as_of": meta["as_of"]}
        got = dict(mem.execute(q1, params).fetchall()[0])
        want = dict(store.execute(q1, params).fetchall()[0])
        for key in ("total", "covered", "inherited", "gaps"):
            assert got[key] == want[key], key
        assert got["requirements"] == want["requirements"]
        assert (got["covered"], got["inherited"], got["gaps"]) == (15, 23, 59)
    finally:
        mem.close()


def test_properties_survive_the_round_trip(exported, store):
    """Dates, booleans and lists keep their types (the queries compare dates and test list membership)."""
    out, _ = exported
    mem = relate.connect(":memory:")
    try:
        for stmt in _statements(out / "data" / "graph.cypher"):
            mem.execute(stmt)
        probe = ("MATCH (e:Evidence {id: 'EV-044'}) RETURN e.expires_at AS d, e.expires_at < date('2026-12-02') AS past")
        assert dict(mem.execute(probe).fetchall()[0]) == dict(store.execute(probe).fetchall()[0])
        pr = "MATCH (p:Proposal {id: 'PR-005'})-[:ABOUT]->(c:Control) RETURN p.status AS s, c.id AS c"
        assert dict(mem.execute(pr).fetchall()[0]) == dict(store.execute(pr).fetchall()[0])
        base = "MATCH (r:Requirement) WHERE 'MODERATE' IN r.baselines RETURN count(r) AS n"
        assert mem.execute(base).fetchall()[0]["n"] == store.execute(base).fetchall()[0]["n"]
    finally:
        mem.close()


def test_queries_are_copied_verbatim(exported):
    out, meta = exported
    for name in meta["queries"]:
        assert (out / "queries" / f"{name}.cypher").read_bytes() == (QUERIES_DIR / f"{name}.cypher").read_bytes()


def test_scorecard_is_optional(tmp_path, monkeypatch):
    missing = tmp_path / "no-scorecard.json"
    monkeypatch.setattr(export_web, "SCORECARD", missing)
    out = tmp_path / "web"
    meta = export_web.export_web(DEFAULT_STORE, out)
    assert meta["has_scorecard"] is False
    assert not (out / "data" / "scorecard.json").exists()

    present = tmp_path / "scorecard.json"
    present.write_text(json.dumps({"kpis": [{"id": "A1", "value": 1}]}), encoding="utf-8")
    monkeypatch.setattr(export_web, "SCORECARD", present)
    meta = export_web.export_web(DEFAULT_STORE, out)
    assert meta["has_scorecard"] is True
    assert json.loads((out / "data" / "scorecard.json").read_text(encoding="utf-8"))["kpis"][0]["id"] == "A1"

    monkeypatch.setattr(export_web, "SCORECARD", missing)  # a stale copy must not linger
    export_web.export_web(DEFAULT_STORE, out)
    assert not (out / "data" / "scorecard.json").exists()


def test_literal_escaping():
    assert export_web.lit('say "hi"\nnow\\') == '"say \\"hi\\"\\nnow\\\\"'
    assert export_web.lit(True) == "true"
    assert export_web.lit(["a", "b"]) == '["a", "b"]'
    import datetime as dt
    assert export_web.lit(dt.date(2026, 12, 2)) == "date('2026-12-02')"
