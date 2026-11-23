"""Self-test of eval/score_agents.py: perfect, empty and wrong fake answers for the three setups,
the comparison rules, the protocol files, and the scripted repeat-rejection run (on throw-away stores)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import relate

from crosswalk import build as B
from crosswalk import proposals as P
from crosswalk import queries as Q

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load("crosswalk_score_agents", ROOT / "eval" / "score_agents.py")
RJ = _load("crosswalk_reject_script", ROOT / "eval" / "agent_compare" / "reject_script.py")
GOLDEN = S.load_golden()
BY_ID = {q["id"]: q for q in GOLDEN}

EXPIRED_PATH = "P-94fd053fec24"    # 800-171:03.05.03 <- CTRL-REAP-6 <- EV-044 (expired 2026-12-01)
PROPOSED_PATH = "P-1a53bde4375b"   # 800-171:03.05.03 <- PR-005 -> CTRL-PWP-4 (pending proposal)


@pytest.fixture(scope="session")
def base_store(tmp_path_factory):
    store = tmp_path_factory.mktemp("score-base") / "crosswalk"
    B.build(store, export=False)
    return store


@pytest.fixture(scope="session")
def valid_path(base_store):
    conn = relate.connect(str(base_store), read_only=True)
    try:
        ex = Q.explain(conn, "800-171:03.03.01")
    finally:
        conn.close()
    ok = [p for p in ex["paths"] if p["valid"]]
    assert ok, "800-171:03.03.01 must have a valid coverage path"
    return ok[0]["path_id"]


def _write(runs: Path, setup: str, rows: list[dict] | None) -> None:
    d = runs / setup
    d.mkdir(parents=True, exist_ok=True)
    (d / "answers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows or []), encoding="utf-8")


def _perfect(valid_path: str, graph: bool) -> list[dict]:
    rows = []
    for q in GOLDEN:
        claims = []
        if graph:
            claims = [{"text": "03.03.01 is covered with valid evidence", "path_ids": [valid_path], "kind": "coverage"},
                      {"text": "03.05.03 is NOT covered: EV-044 expired", "path_ids": [EXPIRED_PATH],
                       "kind": "coverage", "asserts": "invalid"},
                      {"text": "15 of 97 requirements are covered directly", "path_ids": [], "aggregate": True}]
        rows.append({"id": q["id"], "answer_text": "ok", "structured": json.loads(json.dumps(q["expected"])),
                     "claims": claims, "tool_calls": 3})
    return rows


def _wrong_value(v):
    if isinstance(v, list):
        return []
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return v + 1
    if isinstance(v, str):
        return "X"
    return v


def _wrong(graph: bool) -> list[dict]:
    rows = []
    for q in GOLDEN:
        wrong = {k: _wrong_value(v) for k, v in q["expected"].items()}
        claims = []
        if graph and q["id"] == "GQ-05":
            claims = [{"text": "03.05.03 is covered by CTRL-REAP-6", "path_ids": [EXPIRED_PATH], "kind": "coverage"},
                      {"text": "03.05.03 is covered by CTRL-PWP-4", "path_ids": [PROPOSED_PATH], "kind": "coverage"},
                      {"text": "03.05.03 is covered (invented)", "path_ids": ["P-000000000000"]},
                      {"text": "no receipt at all", "path_ids": []}]
        rows.append({"id": q["id"], "answer_text": "wrong", "structured": wrong, "claims": claims, "tool_calls": 5})
    return rows


# --------------------------------------------------------------------------
# comparison rules
# --------------------------------------------------------------------------


def test_comparison_rules():
    eq = S.values_equal
    assert eq(15, 15) and eq(15, 15.0) and eq(15, "15") and not eq(15, 16) and not eq(15, None)
    assert eq(15.46, 15.46) and eq(15.46, "15.46%") and eq(15.46, 15.455) and not eq(15.46, 15.5)
    assert eq(True, True) and eq(False, "false") and not eq(False, 0) and not eq(True, "yes")
    assert eq(["a", "b"], ["b", "a", "a"]) and not eq(["a", "b"], ["a"]) and eq([], []) and not eq([], None)
    assert eq("2026-12-01", " 2026-12-01 ") and not eq("2026-12-01", "2026-12-02")
    rej = [{"control": "C1", "requirement": "R1", "decided_at": "2026-11-20"}]
    assert eq(rej, [{"decided_at": "2026-11-20", "requirement": "R1", "control": "C1", "reason": "extra"}])
    assert not eq(rej, [{"control": "C1", "requirement": "R2", "decided_at": "2026-11-20"}])
    assert eq({"a": 1, "b": 2}, {"a": 1, "b": 2, "c": 3}) and not eq({"a": 1, "b": 2}, {"a": 1})


def test_free_text_key_is_not_scored():
    q = BY_ID["GQ-12"]
    got = dict(q["expected"], reason="something else entirely")
    cmp = S.compare("GQ-12", q["expected"], got)
    assert cmp["correct"] and cmp["keys"]["reason"]["scored"] is False


def test_protocol_files_match_golden_and_hide_answers():
    qs, tpl = S.protocol_rows(GOLDEN)
    qfile = ROOT / "eval" / "agent_compare" / "questions.jsonl"
    tfile = ROOT / "eval" / "agent_compare" / "answer_template.jsonl"
    on_disk = [json.loads(line) for line in qfile.read_text("utf-8").splitlines()]
    assert on_disk == qs, "run: python -I eval/score_agents.py --write-protocol-files"
    assert [json.loads(line) for line in tfile.read_text("utf-8").splitlines()] == tpl
    for q, t in zip(GOLDEN, tpl):
        assert set(t["structured"]) == set(q["expected"])
    blob = qfile.read_text("utf-8")
    for needle in ("15.46", "EV-044", "P-dana-okafor", "CTRL-MCP-13", "2027-01-01"):
        assert needle not in blob  # the expected values never reach the runners


# --------------------------------------------------------------------------
# full scorer on fake runs
# --------------------------------------------------------------------------


def test_perfect_empty_and_wrong_runs(tmp_path, base_store, valid_path):
    runs = tmp_path / "runs"
    _write(runs, "A-spreadsheet", _perfect(valid_path, graph=False))
    _write(runs, "B-graph", _wrong(graph=True))
    _write(runs, "C-graph-checker", _perfect(valid_path, graph=True))
    usage = {"A-spreadsheet": {"tokens_total": 200000, "seconds_total": 400.0},
             "B-graph": {"tokens_total": 100000, "seconds_total": 200.0}}
    res = S.run(runs, usage, base_store, tmp_path / "out")
    a, b, c = (res["setups"][k] for k in "ABC")

    assert a["correct"] == 20 and a["accuracy"] == 1.0 and a["trap_hits"] == 0 and a["wrong_answers_shown"] == 0
    assert "wrong_claims_shown" not in a

    assert c["correct"] == 20 and c["trap_hits"] == 0
    assert c["wrong_claims_shown"] == 0
    assert c["valid_citation_rate"] == 1.0 and c["aggregate_claims"] == 20 and c["uncited_claims"] == 0
    assert c["valid_citations"] == 40

    assert b["correct"] == 0 and b["accuracy"] == 0.0
    assert b["trap_questions"] == sum(1 for q in GOLDEN if q["trap"])
    assert b["trap_hits"] == b["trap_questions"]   # every trapped question is wrong in its trap direction
    assert b["wrong_claims_shown"] == 3            # expired, proposed-only, fabricated; the uncited one is not "wrong"
    assert b["uncited_claims"] == 1 and b["valid_citations"] == 0
    g5 = next(r for r in b["grid"] if r["id"] == "GQ-05")
    assert g5["wrong_claims"] == 3 and not g5["correct"] and g5["trap_hit"]

    md = (tmp_path / "out" / "results.md").read_text("utf-8")
    assert "| Answer accuracy (exact match) | 20/20 (100%) | 0/20 (0%) | 20/20 (100%) |" in md
    assert "Per-question grid" in md and "| GQ-05 | S1 |" in md
    assert "10,000" in md                          # 200000 tokens / 20 questions for setup A
    assert json.loads((tmp_path / "out" / "results.json").read_text("utf-8"))["setups"]["C"]["correct"] == 20


def test_empty_answers_and_missing_setup(tmp_path, base_store):
    runs = tmp_path / "runs"
    _write(runs, "A-spreadsheet", [])
    _write(runs, "B-graph", [])
    res = S.run(runs, None, base_store, tmp_path / "out")
    assert set(res["setups"]) == {"A", "B"}        # C has no file: not run
    for k in "AB":
        s = res["setups"][k]
        assert s["answered"] == 0 and s["correct"] == 0 and s["accuracy"] == 0.0
        assert s["trap_hits"] == 0                  # no answer is not a trap hit
    assert res["setups"]["B"]["wrong_claims_shown"] == 0 and res["setups"]["B"]["valid_citation_rate"] is None
    assert "not run" in (tmp_path / "out" / "results.md").read_text("utf-8")


def test_trap_direction_rules():
    def hit(qid, **got):
        q = BY_ID[qid]
        return S._trap_hit(q, got, S.compare(qid, q["expected"], got))

    assert hit("GQ-05", covered_direct=True, inherited=False)                           # says MFA is covered
    assert not hit("GQ-05", covered_direct=False, inherited=False, evidence="EV-999")  # wrong, not in trap direction
    assert hit("GQ-11", at_risk=True) and not hit("GQ-11", at_risk=False, control="X")
    assert hit("GQ-14", controls=[]) and not hit("GQ-14", controls=["CTRL-MCP-13"])
    assert hit("GQ-12", allowed=True, previously_rejected=False)
    assert not hit("GQ-02", direct=0)                                                   # untrapped: never a trap hit


def test_claim_judgement_with_invalid_assertion(base_store):
    from crosswalk.claims import PathRegistry, check_claims
    conn = relate.connect(str(base_store), read_only=True)
    try:
        claims = [{"text": "not covered, EV-044 expired", "path_ids": [EXPIRED_PATH], "asserts": "invalid"},
                  {"text": "claims failure but cites nothing", "path_ids": [], "asserts": "invalid"}]
        judged, nodes = S._check_answer(conn, PathRegistry(), "GQ-05", claims, check_claims)
    finally:
        conn.close()
    assert judged[0]["valid_citation"] and not judged[0]["wrong"]
    assert judged[1]["uncited"] and not judged[1]["wrong"]
    assert {"CTRL-REAP-6", "EV-044", "800-171:03.05.03"} <= nodes
    assert S.must_cite_hit(["800-171", "EV-044", "EV-999"], nodes) == round(2 / 3, 4)


# --------------------------------------------------------------------------
# repeat rejection
# --------------------------------------------------------------------------


def _propose(store, by, pairs):
    conn = P.open_writer(store)
    try:
        for control, req in pairs:
            P.create_proposal(conn, "map", by, control, req, "evaluation self-test")
    finally:
        conn.close()


def test_repeat_rejection_flow(tmp_path, base_store):
    store = RJ.prepare(tmp_path / "rr", source=base_store)
    s1 = [("CTRL-AOTP-4", "800-53:AC-2"), ("CTRL-AP-11", "800-53:CP-9"), ("CTRL-SDLCP-46", "800-53:SA-11"),
          ("CTRL-REAP-7", "800-53:SC-8"), ("CTRL-LMP-15", "800-53:AU-2")]
    _propose(store, S.S1_AGENT, s1)
    first = RJ.plan(store)
    assert first == RJ.plan(store) and len(first) == 3        # deterministic
    assert [r["score"] for r in first] == sorted(r["score"] for r in first)
    done = RJ.reject(store, out=tmp_path / "rr" / "rejections.json")
    assert done == first and (tmp_path / "rr" / "rejections.json").exists()
    rejected = {(r["control"], r["requirement"]) for r in done}
    assert len(rejected) == 3

    # session 2: a fresh proposal only -> 0 repeats
    logs = tmp_path / "rr" / "logs"
    (logs / "session2_commands.txt").write_text("crosswalk decisions --json\ncrosswalk suggest CTRL-AP-11\n", "utf-8")
    _propose(store, S.S2_AGENT, [("CTRL-AP-12", "800-53:CP-9")])
    clean = S.score_repeat(store, logs)
    assert clean["session2_repeats_of_session1_rejections"] == 0
    assert clean["decisions_called_first"] is True and clean["pass"] is True
    assert len(clean["session1_rejected"]) == 3 and len(clean["session1_proposals"]) == 5

    # a session that re-proposes a rejected mapping, and never read decisions first, fails
    _propose(store, S.S2_AGENT, [sorted(rejected)[0]])
    (logs / "session2_commands.txt").write_text("crosswalk suggest CTRL-AP-11\ncrosswalk decisions\n", "utf-8")
    bad = S.score_repeat(store, logs)
    assert bad["session2_repeats_of_session1_rejections"] == 1
    assert bad["session2_repeats_flagged_by_verifier"] == 1   # the verifier saw the earlier rejection
    assert bad["decisions_called_first"] is False and bad["pass"] is False

    runs = tmp_path / "runs"
    _write(runs, "A-spreadsheet", [])
    res = S.run(runs, None, base_store, tmp_path / "out", repeat_store=store, repeat_logs=logs)
    assert "Session 2 proposals matching a session-1 rejection" in (tmp_path / "out" / "results.md").read_text("utf-8")
    assert res["repeat_rejection"]["pass"] is False

    src = relate.connect(str(base_store), read_only=True)      # the source store gained no proposals
    try:
        n = src.execute("MATCH (p:Proposal) RETURN count(p) AS n").fetchall()[0]["n"]
    finally:
        src.close()
    assert n == 8
