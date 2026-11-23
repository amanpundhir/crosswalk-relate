"""Q5 mapping suggestions: indexes, the four methods, determinism, the query sanitiser, leave-one-out."""

from __future__ import annotations

import logging

import pytest
import relate

from crosswalk import build as B
from crosswalk import embed as E
from crosswalk import suggest as S

CONTROL = "CTRL-AOTP-11"  # has approved mappings, a rejected proposal (PR-001 -> 800-53:AC-17), policy siblings


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    store = tmp_path_factory.mktemp("suggest") / "crosswalk"
    res = B.build(store, export=False)
    assert res.embedded == res.nodes["Requirement"] + res.nodes["Control"], res.warnings
    c = relate.connect(str(store), read_only=True)
    yield c
    c.close()


def _indexes(conn):
    return {r["name"]: r for r in conn.execute("SHOW INDEXES").fetchall()}


def test_search_indexes_exist(conn):
    idx = _indexes(conn)
    assert idx[B.VECTOR_INDEX]["type"] == "VECTOR"
    assert idx[B.VECTOR_INDEX]["properties"] == ["embedding", "framework"]  # filterable by framework
    for name, label, props in B.FULLTEXT_INDEXES:
        assert idx[name]["type"] == "FULLTEXT" and idx[name]["labelsOrTypes"] == [label]
        assert idx[name]["properties"] == props


def test_embeddings_are_384d_on_requirements_and_controls(conn):
    rows = conn.execute(
        "MATCH (n) WHERE n:Requirement OR n:Control RETURN labels(n)[0] AS l, count(n) AS n, "
        "min(size(n.embedding)) AS lo, max(size(n.embedding)) AS hi").fetchall()
    assert {r["l"] for r in rows} == {"Requirement", "Control"}
    assert all(r["lo"] == r["hi"] == 384 for r in rows)


@pytest.mark.parametrize("framework", ["800-53", "800-171", "CSF"])
@pytest.mark.parametrize("method", S.METHODS)
def test_each_method_returns_k_from_the_right_framework(conn, method, framework):
    res = S.suggest(conn, CONTROL, framework, 7, method)
    if method == "fulltext" and framework == "CSF":
        assert 1 <= len(res) <= 7  # keyword match is sparse on CSF's short statements (no stemming)
    else:
        assert len(res) == 7
    assert all(r["id"].startswith(f"{framework}:") for r in res)
    assert len({r["id"] for r in res}) == len(res)
    assert all(r["method"] == method and r["title"] for r in res)
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_signals_are_per_method_contributions(conn):
    for r in S.suggest(conn, CONTROL, "800-53", 10, "hybrid"):
        sig = r["signals"]
        assert set(sig) <= {"vector", "fulltext"} and sig
        assert r["score"] == pytest.approx(sum(s["contribution"] for s in sig.values()))
    top = S.suggest(conn, CONTROL, "800-53", 1, "vector")[0]
    assert top["signals"]["vector"]["rank"] == 1


def test_hybrid_matches_manual_rrf(conn):
    vec = S.suggest(conn, CONTROL, "800-53", S.POOL, "vector")
    ft = S.suggest(conn, CONTROL, "800-53", S.POOL, "fulltext")
    want: dict[str, float] = {}
    for i, r in enumerate(vec, 1):
        want[r["id"]] = want.get(r["id"], 0) + S.W_VEC / (S.RRF_C + i)
    for i, r in enumerate(ft, 1):
        want[r["id"]] = want.get(r["id"], 0) + S.W_FT / (S.RRF_C + i)
    ranked = sorted(want.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    got = S.suggest(conn, CONTROL, "800-53", 10, "hybrid")
    assert [r["id"] for r in got] == [i for i, _ in ranked]
    assert [r["score"] for r in got] == pytest.approx([s for _, s in ranked])


def test_deterministic(conn):
    for method in S.METHODS:
        a = S.suggest(conn, CONTROL, "800-53", 10, method)
        b = S.suggest(conn, CONTROL, "800-53", 10, method)
        assert a == b


def test_graph_rerank_reports_paths(conn):
    res = S.suggest(conn, CONTROL, "800-53", 30, "hybrid+graph")
    used = [r for r in res if "graph" in r["signals"]]
    assert used, "expected at least one candidate with a graph signal"
    for r in used:
        assert r["paths"] and r["path_id"] == r["paths"][0]["id"] and r["path_id"].startswith("P-")
        assert {p["signal"] for p in r["paths"]} <= {"family", "crosswalk", "rejected"}
        for p in r["paths"]:  # every path is replayable by the claim checker's path check
            from crosswalk import queries as Q
            assert p["nodes"][-1] == f"Requirement:{r['id']}"
            assert Q.check_path(conn, p["nodes"], p["rels"])["exists"]
    assert all(r["paths"] == [] and r["path_id"] is None for r in res if "graph" not in r["signals"])


def test_rejected_decision_penalises_candidate(conn):
    sig = S.graph_signals(conn, CONTROL, "800-53", ignore_own=False)
    assert "800-53:AC-17" in sig["rejected"]  # PR-001 / D-001
    kept = {r["id"]: r for r in S.suggest(conn, CONTROL, "800-53", 30, "hybrid+graph", ignore_own=False)}
    loo = {r["id"]: r for r in S.suggest(conn, CONTROL, "800-53", 30, "hybrid+graph", ignore_own=True)}
    penalised = [i for i, r in kept.items() if "rejected" in r["signals"].get("graph", {})]
    for i in penalised:
        assert kept[i]["signals"]["graph"]["rejected"]["contribution"] < 0
        assert kept[i]["score"] < loo[i]["score"]
        assert any(p["signal"] == "rejected" and p["nodes"][1].startswith("Proposal:") for p in kept[i]["paths"])


def test_leave_one_out_really_excludes_the_controls_own_edges(conn):
    own_sat = {r["q"] for r in conn.execute(
        "MATCH (:Control {id: $c})-[:SATISFIES]->(q:Requirement) RETURN q.id AS q", {"c": CONTROL}).fetchall()}
    assert own_sat, "the test control must have approved mappings"

    full = S.graph_signals(conn, CONTROL, "800-53", ignore_own=False)
    loo = S.graph_signals(conn, CONTROL, "800-53", ignore_own=True)

    # crosswalk and rejection signals come only from the control's own edges: gone in leave-one-out
    assert loo["crosswalk"] == {} and loo["rejected"] == {}
    assert full["crosswalk"] or full["rejected"]

    # the family signal comes from sibling controls only; no path starts a SATISFIES at the control itself
    for fam, via in loo["family"].items():
        for v in via:
            assert v["sibling"] != CONTROL
            assert v["nodes"][0] == f"Control:{CONTROL}" and v["nodes"][2] == f"Control:{v['sibling']}"
            assert v["nodes"][2] != f"Control:{CONTROL}"

    # and through suggest(): no path of any suggestion uses the control's own SATISFIES edge or proposals
    for r in S.suggest(conn, CONTROL, "800-53", 30, "hybrid+graph", ignore_own=True):
        assert set(r["signals"].get("graph", {})) <= {"family"}
        for p in r["paths"]:
            assert p["signal"] == "family"
            assert p["rels"][0] == "MANDATES<-"  # starts at the policy, never at the control's own SATISFIES
            assert not any(n.startswith("Proposal:") for n in p["nodes"])


def test_leave_one_out_changes_the_ranking_only_through_own_edges(conn):
    a = S.suggest(conn, CONTROL, "800-53", 30, "hybrid+graph", ignore_own=True)
    b = S.suggest(conn, CONTROL, "800-53", 30, "hybrid+graph", ignore_own=False)
    assert {r["id"] for r in a} == {r["id"] for r in b}  # same candidate pool
    assert any("crosswalk" in r["signals"].get("graph", {}) or "rejected" in r["signals"].get("graph", {})
               for r in b)
    assert not any("crosswalk" in r["signals"].get("graph", {}) or "rejected" in r["signals"].get("graph", {})
                   for r in a)


# --------------------------------------------------------------------------
# sanitiser
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    None, "", "   ", "AND", "OR NOT AND", "(", ")", '"', "'", "*", "?", "~", "^", ":", "\\",
    'foo* "bar baz" (qux)~2^3 title:text AND NOT [x TO y] {z}', "a/b c+d -e !f", "C++ & über 中文 \U0001f600",
    "x" * 10_000, " ".join(f"w{i}" for i in range(500)), "line1\nline2\ttab\x00nul",
])
def test_sanitiser_output_is_plain_words(raw):
    out = S.sanitise_query(raw)
    assert all(ch.isalnum() and ch.isascii() and not ch.isupper() or ch == " " for ch in out)
    assert not {"and", "or", "not"} & set(out.split())
    assert len(out.split()) <= S.MAX_QUERY_TERMS


def test_sanitiser_keeps_content_words_once():
    assert S.sanitise_query('Review "accounts" AND review (Permissions)* monthly~2') == "review accounts permissions monthly"
    assert S.sanitise_query(None) == "" and S.sanitise_query("AND OR NOT") == ""


@pytest.mark.parametrize("raw", ['(', 'AND', 'a:"b', "***", "~~", "x^", '"unterminated'])
def test_odd_input_never_breaks_a_fulltext_search(conn, raw):
    q = S.sanitise_query(raw)
    rows = conn.execute(S._text("q5_suggest_fulltext"),
                        {"q": q or "zzzz", "framework": "800-53", "k": 5, "ft_pool": S.FT_POOL}).fetchall()
    assert isinstance(rows, list)


def test_operator_only_control_text_gives_empty_query():
    c = {"id": "X", "text": 'AND (OR) "NOT" *~^: ' * 3, "context": None, "embedding": None}
    assert S.sanitise_query(E.control_text(c)) == ""


# --------------------------------------------------------------------------
# errors and degraded mode
# --------------------------------------------------------------------------


def test_errors(conn):
    with pytest.raises(S.SuggestError):
        S.suggest(conn, "CTRL-NOPE", "800-53", 5)
    with pytest.raises(S.SuggestError):
        S.suggest(conn, CONTROL, "NOPE-1", 5)
    with pytest.raises(S.SuggestError):
        S.suggest(conn, CONTROL, "800-53", 5, "magic")


def test_embedding_cache_roundtrip_is_4_decimals():
    vec = [0.12345678, -0.9999999, 0.0, 1.0] + [0.5] * 380
    back = E._decode(E._encode(vec))
    assert back[:4] == [0.1235, -1.0, 0.0, 1.0] and len(back) == 384


def test_cache_is_committed_and_small():
    assert E.CACHE_PATH.is_file() and E.CACHE_PATH.stat().st_size < 10_000_000
    cache = E.load_cache()
    s = B.load_sources()
    items = [(r["id"], E.requirement_text(r)) for r in s.requirements] + [(c["id"], E.control_text(c)) for c in s.controls]
    assert all(cache.get(i, {}).get("sha") == E.text_sha(t) for i, t in items), "cache is stale: run crosswalk build"


def test_build_without_model_or_cache_still_works(tmp_path, monkeypatch, caplog):
    def no_model():
        raise RuntimeError("model not available")

    monkeypatch.setattr(E, "CACHE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(E, "_get_model", no_model)
    with caplog.at_level(logging.WARNING):
        res = B.build(tmp_path / "bare", export=False)
    assert res.embedded == 0 and res.warnings
    assert any("no embedding" in r.message or "unavailable" in r.message for r in caplog.records)
    c = relate.connect(str(tmp_path / "bare"), read_only=True)
    try:
        names = {r["name"] for r in c.execute("SHOW INDEXES").fetchall()}
        assert B.VECTOR_INDEX not in names and "requirement_text_ft" in names
        assert len(S.suggest(c, CONTROL, "800-53", 5, "fulltext")) == 5
        with pytest.raises(S.SuggestError):
            S.suggest(c, CONTROL, "800-53", 5, "hybrid")
    finally:
        c.close()
