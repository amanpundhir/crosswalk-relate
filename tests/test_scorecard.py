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
