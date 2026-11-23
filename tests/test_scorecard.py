"""crosswalk scorecard (quick mode): key metrics exist, core correctness and guardrails pass, no files written."""

from __future__ import annotations

import pytest

from crosswalk import scorecard as S

REPO = S.ROOT
pytestmark = pytest.mark.skipif(not (REPO / "data" / "crosswalk" / "manifest.json").exists(), reason="no built store")


@pytest.fixture(scope="module")
def sc():
    return S.run("data/crosswalk", quick=True, write=False)


def metrics(sc):
    return {m["id"]: m for sec in sc["sections"] for m in sec["metrics"]}


def test_all_sections_and_headline_present(sc):
    assert [s["id"] for s in sc["sections"]] == list("DCBAEF")
    assert len(sc["headline"]) == 4
    assert all(m["status"] in ("pass", "miss", "info") and {"name", "value", "target", "source"} <= set(m)
               for m in metrics(sc).values())
    for key in ("query_latency", "query_p95_worst_ms", "claim_check_ms_live_catch"):
        assert key in sc["timings"]


def test_core_correctness_all_pass(sc):
    m = metrics(sc)
    for mid in ("D1", "D1b", "D1c", "D2", "D3", "D4", "D5"):
        assert m[mid]["status"] == "pass", m[mid]
    assert m["D4"]["value"] == 0


def test_guardrails_pass(sc):
    m = metrics(sc)
    for mid in ("C1", "C1b", "C2", "C3", "C5"):
        assert m[mid]["status"] == "pass", m[mid]
    assert m["C5"]["value"] == 0
    assert m["C6"]["status"] == "info"  # skipped in quick mode


def test_recorded_agent_numbers(sc):
    m = metrics(sc)
    assert m["A3"]["status"] == "pass" and m["A5"]["value"] == 0 and m["A6"]["value"] == 0
    assert m["C4"]["status"] == "pass"
    assert "E1" in m and "E4" in m and m["E4"]["value"] == 44


def test_markdown_renders(sc):
    md = S.render_markdown(sc)
    assert "## Headline" in md and "## D. Core correctness" in md and "Timings" in md


def test_full_scorecard_without_relate_cli(monkeypatch):
    """The no-AI path installs only the Python package: the served concurrency half is skipped, not a crash."""
    from crosswalk import build as B
    from crosswalk import demo_concurrency as D

    def no_cli():
        raise B.BuildError("the relate CLI was not found (expected next to the Python interpreter)")

    monkeypatch.setattr(D, "_relate_cli", no_cli)
    monkeypatch.setattr(B, "_relate_cli", no_cli)
    store = REPO / "data" / "crosswalk"
    _, timings = S.section_f(store, False)
    c6 = {m["id"]: m for m in S.section_c(store, False, None, timings)}["C6"]
    assert c6["status"] == "pass" and c6["value"] == "0/2", c6
    assert "embedded only" in c6["name"] and "server: skipped" in c6["note"]
    f3 = {m["id"]: m for m in S.timing_metrics(timings, False)}["F3"]
    assert f3["status"] == "info" and "relate CLI is not installed" in f3["value"], f3
