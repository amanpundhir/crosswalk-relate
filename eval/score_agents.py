"""Score the three-column agent comparison (docs/plan/05 section A) and the repeat-rejection run (section C).

    python -I eval/score_agents.py [--runs eval/agent-runs] [--usage usage.json] [--store data/crosswalk]
                                   [--out-dir eval/agent_compare] [--repeat-store PATH] [--repeat-logs DIR]
    python -I eval/score_agents.py --write-protocol-files      # regenerates questions.jsonl + answer_template.jsonl

Inputs: ``<runs>/<setup>/answers.jsonl`` for the setups ``A-spreadsheet``, ``B-graph``, ``C-graph-checker``
(one JSON object per line, schema in eval/agent_compare/README.md), ``eval/golden_questions.yaml`` (never shown
to the runners) and, for the claim checks, a Crosswalk store opened read-only.
Outputs: ``<out-dir>/results.json`` and ``<out-dir>/results.md``.

Comparison rules (``structured`` against the question's ``expected``; extra keys in the answer are ignored,
a missing key or null is wrong):

* bool        exact (the strings "true"/"false" are accepted)
* integer     exact
* float       absolute tolerance 0.01 (percentages are given with two decimals)
* string      exact after trimming (ids, dates ``YYYY-MM-DD``)
* list of str set equality (order and duplicates ignored; ``[]`` must be given as ``[]``)
* list of dict set equality of the tuples of the expected keys of each element (extra keys ignored)
* dict        same keys, every value compared by these rules
* free-text keys (``FREE_TEXT``) are reported but not scored

A question is correct when every scored key matches.  A *trap hit* needs ``trap`` set on the question and the
answer wrong in the direction the planted scenario pulls (``_trap_hit``; the default is "answer not correct").

Claims (setups B and C only; claim = ``{text, path_ids, kind?, asserts?, aggregate?}``) are re-run with
``crosswalk.claims.check_claims``:

* ``aggregate: true`` (or ``kind: "aggregate"``) claims restate a tool total that has no path; they are counted
  but neither checked nor included in the citation rate.
* ``asserts`` is ``"valid"`` (default: the claim says the cited path holds now) or ``"invalid"`` (the claim cites a
  failing path to show something does NOT hold, e.g. "not covered, EV-044 expired").
* valid citation: ``valid`` and the checker verdict is verified; ``invalid`` and at least one cited path is not ok
  and none is unknown.
* wrong claim shown: ``valid`` and verdict failed or partial (expired, only proposed, rejected, not adopted,
  fabricated or missing path); ``invalid`` and every cited path re-runs ok, or one is unknown.
* uncited: a non-aggregate claim with no path id (not wrong, but not a valid citation either).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))  # python -I ignores PYTHONPATH

import yaml  # noqa: E402

GOLDEN = REPO / "eval" / "golden_questions.yaml"
RUNS = REPO / "eval" / "agent-runs"
OUT_DIR = REPO / "eval" / "agent_compare"
SETUPS = {"A": "A-spreadsheet", "B": "B-graph", "C": "C-graph-checker"}
SETUP_TITLES = {"A": "A. Spreadsheet agent (CSV export)", "B": "B. Graph agent, no claim check",
                "C": "C. Graph agent + claim checker"}
FLOAT_TOL = 0.01
FREE_TEXT = {("GQ-12", "reason")}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --------------------------------------------------------------------------
# protocol files shown to the runners: question text + the keys of ``structured`` (never the values)
# --------------------------------------------------------------------------

HINTS: dict[tuple[str, str], str] = {
    ("GQ-01", "active_requirements"): "number of active 800-171 requirements in the framework",
    ("GQ-01", "direct"): "requirements covered directly (approved mapping from an adopted control + valid evidence)",
    ("GQ-01", "inherited"): "requirements not direct but met through a one-hop crosswalk neighbour that is covered",
    ("GQ-01", "gap"): "requirements neither direct nor inherited",
    ("GQ-01", "percent_direct"): "percent, 2 decimals, e.g. 12.34",
    ("GQ-01", "percent_direct_plus_inherited"): "percent, 2 decimals",
    ("GQ-02", "percent_direct"): "percent, 2 decimals",
    ("GQ-03", "percent_direct_plus_inherited"): "percent, 2 decimals",
    ("GQ-04", "requirements"): "ids like 800-171:03.01.01",
    ("GQ-05", "covered_direct"): "true only if an approved mapping with currently valid evidence exists",
    ("GQ-05", "inherited"): "true only if met through a covered one-hop neighbour",
    ("GQ-05", "evidence"): "evidence id on the control's approved path to this requirement",
    ("GQ-05", "evidence_expired_at"): "date YYYY-MM-DD",
    ("GQ-05", "approved_control_with_valid_evidence"): "control ids; [] if none",
    ("GQ-05", "proposed_only_controls"): "control ids linked to the requirement only by a pending proposal",
    ("GQ-07", "broken_800_171"): "800-171 requirements that lose direct coverage",
    ("GQ-08", "cutoff"): "as_of plus 30 days, YYYY-MM-DD",
    ("GQ-08", "expiring_evidence"): "evidence valid today that expires on or before the cutoff",
    ("GQ-08", "affected_audits"): "audit ids",
    ("GQ-08", "broken_counts"): "object with keys 800-53, 800-171, CSF: requirements losing direct coverage",
    ("GQ-09", "still_inherited"): "broken requirements still met through a covered one-hop neighbour",
    ("GQ-09", "broken_and_not_inherited"): "broken requirements with no covered neighbour either",
    ("GQ-11", "at_risk"): "true if the requirement behind this control would lose coverage",
    ("GQ-11", "control"): "control id the evidence belongs to",
    ("GQ-11", "requirement_still_covered"): "requirement id, e.g. 800-53:AC-2",
    ("GQ-11", "valid_replacements"): "evidence ids still valid for that control or requirement",
    ("GQ-11", "in_blast_30d"): "true if this requirement loses coverage within the 30-day window",
    ("GQ-11", "in_blast_until_audit_171"): "true if it loses coverage before the 800-171 audit date",
    ("GQ-12", "allowed"): "true if this mapping may be proposed again",
    ("GQ-12", "previously_rejected"): "true if a human rejected this exact mapping before",
    ("GQ-12", "decided_by"): "person id, e.g. P-xxx-yyy",
    ("GQ-12", "decided_at"): "date YYYY-MM-DD",
    ("GQ-12", "reason"): "the reason recorded with the earlier decision (free text, not scored)",
    ("GQ-13", "rejections"): "one object per earlier rejection: control, requirement, decided_at",
    ("GQ-15", "person"): "person id",
    ("GQ-15", "sole_owned_count"): "controls where she is the only owner",
    ("GQ-15", "controls"): "those control ids",
    ("GQ-15", "high_criticality_systems"): "ids of high-criticality systems those controls apply to",
    ("GQ-16", "requirements"): "requirement ids (any framework) whose every covering control is sole-owned by her",
    ("GQ-17", "evidence"): "evidence id",
    ("GQ-17", "direct_requirements"): "distinct requirements it proves directly through its controls",
    ("GQ-17", "frameworks_direct"): "framework names: 800-53, 800-171, CSF",
    ("GQ-17", "frameworks_reached"): "framework names reached directly or through one crosswalk hop",
    ("GQ-17", "reach_count_1_hop"): "distinct requirements reached directly or through one crosswalk hop",
    ("GQ-17", "requested_by"): "audit ids that request it",
    ("GQ-20", "covered_direct"): "true if an approved mapping with currently valid evidence exists",
    ("GQ-20", "paths"): "one object per covering path: control, evidence, expires_at, valid (bool)",
}


def describe(value: Any) -> Any:
    """Type descriptor of an expected value (the shape of ``structured``, never the value)."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "date YYYY-MM-DD" if _DATE.match(value) else "string"
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return [describe(value[0])]
        return ["string"] if (not value or isinstance(value[0], str)) else [describe(value[0])]
    if isinstance(value, dict):
        return {k: describe(v) for k, v in value.items()}
    return "any"


def load_golden(path: Path = GOLDEN) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def protocol_rows(golden: list[dict]) -> tuple[list[dict], list[dict]]:
    """(questions, template) rows for ``questions.jsonl`` and ``answer_template.jsonl``."""
    qs, tpl = [], []
    for q in golden:
        keys = {k: describe(v) for k, v in q["expected"].items()}
        hints = {k: HINTS[(q["id"], k)] for k in q["expected"] if (q["id"], k) in HINTS}
        qs.append({"id": q["id"], "question": q["question"], "structured_keys": keys, "key_hints": hints})
        tpl.append({"id": q["id"], "answer_text": "", "structured": {k: _placeholder(v) for k, v in keys.items()},
                    "claims": [{"text": "", "path_ids": [], "kind": "coverage", "asserts": "valid"}],
                    "tool_calls": 0})
    return qs, tpl


def _placeholder(desc: Any) -> Any:
    if isinstance(desc, dict):
        return {k: _placeholder(v) for k, v in desc.items()}
    if isinstance(desc, list):
        return []
    return None


def write_protocol_files(out_dir: Path = OUT_DIR, golden_path: Path = GOLDEN) -> None:
    qs, tpl = protocol_rows(load_golden(golden_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("questions.jsonl", qs), ("answer_template.jsonl", tpl)):
        with (out_dir / name).open("w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().rstrip("%").replace(",", ""))
        except ValueError:
            return None
    return None


def _bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return None


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _tuple(el: Any, keys: list[str]) -> tuple:
    el = el if isinstance(el, dict) else {}
    out = []
    for k in keys:
        v = el.get(k)
        b = _bool(v) if isinstance(v, str) else None
        out.append(b if b is not None else _norm(v))
    return tuple(out)


def values_equal(exp: Any, got: Any) -> bool:
    if exp is None:
        return got is None
    if got is None:
        return False
    if isinstance(exp, bool):
        return _bool(got) is exp
    if isinstance(exp, (int, float)):
        g = _num(got)
        if g is None:
            return False
        if isinstance(exp, float) and not float(exp).is_integer():
            return abs(g - exp) <= FLOAT_TOL + 1e-9
        return abs(g - exp) < 1e-9
    if isinstance(exp, str):
        return isinstance(got, str) and got.strip() == exp.strip()
    if isinstance(exp, list):
        if not isinstance(got, list):
            return False
        if exp and isinstance(exp[0], dict):
            keys = sorted({k for el in exp for k in el})
            return {_tuple(e, keys) for e in exp} == {_tuple(g, keys) for g in got}
        try:
            return {str(x).strip() for x in exp} == {str(x).strip() for x in got}
        except TypeError:
            return False
    if isinstance(exp, dict):
        return (isinstance(got, dict) and set(exp) <= set(got)
                and all(values_equal(v, got.get(k)) for k, v in exp.items()))
    return exp == got


def compare(qid: str, expected: dict, structured: Any) -> dict:
    """Per-key verdicts: ``{key: {"ok": bool, "scored": bool}}`` plus ``correct`` and ``key_score``."""
    structured = structured if isinstance(structured, dict) else {}
    keys = {}
    for k, v in expected.items():
        ok = values_equal(v, structured.get(k))
        keys[k] = {"ok": ok, "scored": (qid, k) not in FREE_TEXT}
    scored = [x for x in keys.values() if x["scored"]]
    correct = bool(scored) and all(x["ok"] for x in scored)
    return {"keys": keys, "correct": correct,
            "key_score": round(sum(x["ok"] for x in scored) / len(scored), 4) if scored else 0.0}


def _set(v: Any) -> set | None:
    return {str(x).strip() for x in v} if isinstance(v, list) else None


def _missing_any(expected: Any, got: Any) -> bool:
    g = _set(got)
    return g is None or not set(map(str, expected)) <= g


def _trap_hit(q: dict, structured: dict, cmp: dict) -> bool:
    """Answer wrong in the direction the planted scenario pulls (see the module docstring)."""
    if not q.get("trap") or cmp["correct"]:
        return False
    e, g = q["expected"], structured or {}
    ok = {k: v["ok"] for k, v in cmp["keys"].items()}
    qid = q["id"]
    if qid == "GQ-03":                      # S5: inheritance missed or counted as direct
        return not (ok["inherited"] and ok["direct"])
    if qid == "GQ-04":                      # S5: the inherited set is wrong
        return not (ok["requirements"] and ok["count"])
    if qid == "GQ-05":                      # S1: says MFA is covered (trusts the tracker or the proposal)
        return _bool(g.get("covered_direct")) is True or _bool(g.get("inherited")) is True or bool(
            g.get("approved_control_with_valid_evidence"))
    if qid == "GQ-06":                      # S1: trusts the legacy tracker, misses a stale "Compliant"
        return _missing_any(e["controls"], g.get("controls"))
    if qid == "GQ-07":                      # S2: wrong expiring set or broken count
        return not (ok["evidence"] and ok["broken_800_171_count"])
    if qid == "GQ-08":                      # S2: wrong 30-day window (e.g. adds EV-101)
        return not (ok["expiring_evidence"] and ok["cutoff"])
    if qid == "GQ-09":                      # S2: inherited / not-inherited split wrong
        return not (ok["still_inherited"] and ok["broken_and_not_inherited"])
    if qid == "GQ-11":                      # S6: raises an alarm on the decoy
        return _bool(g.get("at_risk")) is True
    if qid == "GQ-12":                      # S4: allows a mapping a human rejected
        return _bool(g.get("allowed")) is True or _bool(g.get("previously_rejected")) is not True
    if qid == "GQ-13":                      # S4: forgets a rejection
        return _missing_any([f"{r['control']}|{r['requirement']}" for r in e["rejections"]],
                            [f"{r.get('control')}|{r.get('requirement')}" for r in g.get("rejections") or []
                             if isinstance(r, dict)])
    if qid == "GQ-14":                      # S8: trusts the tracker's owner and misses the unowned control
        return _missing_any(e["controls"], g.get("controls"))
    if qid == "GQ-15":                      # S3: wrong sole-ownership picture
        return not (ok["sole_owned_count"] and ok["controls"])
    if qid == "GQ-16":                      # S3: wrong set of orphaned requirements
        return not ok["requirements"]
    if qid == "GQ-17":                      # S7: names a different evidence item
        return not ok["evidence"]
    return True                             # default: any wrong answer on a trapped question


# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------


def _is_aggregate(c: dict) -> bool:
    return bool(c.get("aggregate")) or str(c.get("kind", "")).lower() == "aggregate"


def _asserts(c: dict) -> str:
    return "invalid" if str(c.get("asserts", "valid")).strip().lower() in ("invalid", "false", "fails") else "valid"


def judge_claim(claim: dict, checked: dict) -> dict:
    """Classify one checked claim: ``wrong`` / ``valid_citation`` / ``uncited``."""
    paths = checked["paths"]
    if not paths:
        return {"wrong": False, "valid_citation": False, "uncited": True}
    if _asserts(claim) == "valid":
        good = checked["verdict"] == "verified"
        return {"wrong": not good, "valid_citation": good, "uncited": False}
    unknown = any(p["code"] == "unknown_path" for p in paths)
    failing = any(p["status"] != "ok" for p in paths)
    good = failing and not unknown
    return {"wrong": not good, "valid_citation": good, "uncited": False}


def _check_answer(conn, registry, qid: str, claims: list, check_claims) -> tuple[list[dict], set[str]]:
    """Run the non-aggregate claims; returns (per-claim judgements, node ids on the cited paths)."""
    real = [c for c in claims if isinstance(c, dict) and not _is_aggregate(c)]
    nodes: set[str] = set()
    out: list[dict] = []
    if not real:
        return out, nodes
    checked = check_claims(conn, {"question": qid, "agent": "eval", "claims": real}, registry)
    for c, ck in zip(real, checked["claims"]):
        j = judge_claim(c, ck)
        j.update({"text": str(c.get("text", ""))[:200], "verdict": ck["verdict"],
                  "reason": ck["reason"] if ck["verdict"] != "verified" else ""})
        out.append(j)
        for p in ck["paths"]:
            for n in p.get("nodes") or []:
                nodes.add(n.partition(":")[2] or n)
    return out, nodes


def must_cite_hit(must_cite: list[str], nodes: set[str]) -> float:
    if not must_cite:
        return 1.0
    hit = 0
    for m in must_cite:
        if m in nodes or any(n.startswith(m + ":") for n in nodes):
            hit += 1
    return round(hit / len(must_cite), 4)


# --------------------------------------------------------------------------
# scoring a setup
# --------------------------------------------------------------------------


def load_answers(path: Path) -> dict[str, dict]:
    """``id -> answer`` (the last line for an id wins); a missing file gives an empty dict."""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{n}: not valid JSON ({exc})")
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = row
    return out


def score_setup(letter: str, answers: dict[str, dict], golden: list[dict], conn=None, check_claims=None,
                registry_factory=None) -> dict:
    graph = letter in ("B", "C")
    registry = registry_factory() if (graph and registry_factory) else None
    grid = []
    tot = {"claims": 0, "aggregate": 0, "cited": 0, "uncited": 0, "valid_citations": 0, "wrong": 0}
    draft = {"wrong": 0, "questions_with_draft": 0}
    correct = traps = trapped = 0
    tool_calls, check_calls, key_scores, cite_scores = [], [], [], []
    for q in golden:
        a = answers.get(q["id"])
        row = {"id": q["id"], "trap": q.get("trap"), "answered": a is not None}
        if a is None:
            row.update({"correct": False, "key_score": 0.0, "trap_hit": False, "claims": 0, "wrong_claims": 0})
            grid.append(row)
            if q.get("trap"):
                trapped += 1
            key_scores.append(0.0)
            continue
        cmp = compare(q["id"], q["expected"], a.get("structured"))
        hit = _trap_hit(q, a.get("structured") or {}, cmp)
        claims = a.get("claims") if isinstance(a.get("claims"), list) else []
        row.update({"correct": cmp["correct"], "key_score": cmp["key_score"], "trap_hit": hit,
                    "wrong_keys": [k for k, v in cmp["keys"].items() if v["scored"] and not v["ok"]],
                    "claims": len(claims), "wrong_claims": 0})
        correct += cmp["correct"]
        trapped += bool(q.get("trap"))
        traps += hit
        key_scores.append(cmp["key_score"])
        if isinstance(a.get("tool_calls"), (int, float)):
            tool_calls.append(float(a["tool_calls"]))
        if isinstance(a.get("check_calls"), (int, float)):
            check_calls.append(float(a["check_calls"]))
        if graph and conn is not None:
            judged, nodes = _check_answer(conn, registry, q["id"], claims, check_claims)
            row["wrong_claims"] = sum(j["wrong"] for j in judged)
            row["claim_detail"] = [j for j in judged if j["wrong"]]
            row["must_cite_hit"] = must_cite_hit(q.get("must_cite", []), nodes)
            cite_scores.append(row["must_cite_hit"])
            tot["claims"] += len(judged) + sum(1 for c in claims if isinstance(c, dict) and _is_aggregate(c))
            tot["aggregate"] += sum(1 for c in claims if isinstance(c, dict) and _is_aggregate(c))
            tot["uncited"] += sum(j["uncited"] for j in judged)
            tot["cited"] += sum(not j["uncited"] for j in judged)
            tot["valid_citations"] += sum(j["valid_citation"] for j in judged)
            tot["wrong"] += row["wrong_claims"]
            dc = a.get("draft_claims")
            if isinstance(dc, list):
                dj, _ = _check_answer(conn, registry, q["id"], dc, check_claims)
                row["draft_wrong_claims"] = sum(j["wrong"] for j in dj)
                draft["wrong"] += row["draft_wrong_claims"]
                draft["questions_with_draft"] += 1
        grid.append(row)
    n = len(golden)
    checkable = tot["claims"] - tot["aggregate"]
    res = {
        "setup": SETUPS[letter], "title": SETUP_TITLES[letter], "questions": n,
        "answered": sum(1 for r in grid if r["answered"]), "correct": correct,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "mean_key_score": round(sum(key_scores) / n, 4) if n else 0.0,
        "wrong_answers_shown": sum(1 for r in grid if r["answered"] and not r["correct"]),
        "trap_questions": trapped, "trap_hits": traps,
        "tool_calls_total": sum(tool_calls) if tool_calls else None,
        "tool_calls_per_question": round(sum(tool_calls) / len(tool_calls), 2) if tool_calls else None,
        "grid": grid,
    }
    if graph:
        res.update({
            "claims_total": tot["claims"], "aggregate_claims": tot["aggregate"], "cited_claims": tot["cited"],
            "uncited_claims": tot["uncited"], "valid_citations": tot["valid_citations"],
            "valid_citation_rate": round(tot["valid_citations"] / checkable, 4) if checkable else None,
            "wrong_claims_shown": tot["wrong"],
            "mean_must_cite_hit": round(sum(cite_scores) / len(cite_scores), 4) if cite_scores else None,
        })
    if letter == "C":
        res.update({"check_calls_total": sum(check_calls) if check_calls else None,
                    "draft_wrong_claims": draft["wrong"] if draft["questions_with_draft"] else None,
                    "draft_wrong_claims_caught": (draft["wrong"] - tot["wrong"]) if draft["questions_with_draft"] else None})
    return res


# --------------------------------------------------------------------------
# repeat rejection (docs/plan/05 section C)
# --------------------------------------------------------------------------

S1_AGENT, S2_AGENT = "mapper-s1", "mapper-s2"


def _pair(p: dict) -> tuple[str, str]:
    return (p["about"], p["target"])


def score_repeat(store: str | Path, logs_dir: Path | None = None) -> dict:
    """Read the temp store after both sessions (read-only) and count session-2 repeats of session-1 rejections."""
    import relate

    from crosswalk import proposals as P
    from crosswalk import review as R

    conn = relate.connect(str(store), read_only=True)
    try:
        props = P.list_proposals(conn)
        decs = R.decisions(conn)
    finally:
        conn.close()
    s1 = [p for p in props if p.get("by") == S1_AGENT and p.get("kind") == "map"]
    s2 = [p for p in props if p.get("by") == S2_AGENT and p.get("kind") == "map"]
    s1_ids, s2_ids = {p["id"] for p in s1}, {p["id"] for p in s2}
    rejected = [d for d in decs if d["outcome"] == "rejected" and d["proposal"] in s1_ids]
    rej_pairs = {(d["about"], d["target"]) for d in rejected}
    pre_rej = {(d["about"], d["target"]) for d in decs
               if d["outcome"] == "rejected" and d["proposal"] not in s1_ids | s2_ids}
    rej_ids = {d["proposal"] for d in rejected}
    s1_kept = {_pair(p) for p in s1 if p["id"] not in rej_ids}
    s2_repeats = [p for p in s2 if _pair(p) in rej_pairs]
    s2_pre = [p for p in s2 if _pair(p) in pre_rej]
    s1_pre = [p for p in s1 if _pair(p) in pre_rej]
    s2_dups = [p for p in s2 if _pair(p) in s1_kept]
    flagged = [p for p in s2_repeats if p.get("verified") is False]
    out = {
        "session1_proposals": [{"id": p["id"], "control": p["about"], "requirement": p["target"]} for p in s1],
        "session1_rejected": [{"proposal": d["proposal"], "control": d["about"], "requirement": d["target"],
                               "reason": d["reason"], "by": d["by"]} for d in rejected],
        "session2_proposals": [{"id": p["id"], "control": p["about"], "requirement": p["target"]} for p in s2],
        "session1_repeats_of_preexisting_rejections": len(s1_pre),
        "session2_repeats_of_session1_rejections": len(s2_repeats),
        "session2_repeat_pairs": [{"control": p["about"], "requirement": p["target"]} for p in s2_repeats],
        "session2_repeats_flagged_by_verifier": len(flagged),
        "session2_duplicates_of_session1_pending": len(s2_dups),
        "session2_repeats_of_preexisting_rejections": len(s2_pre),
        "target_session2": 0,
        "decisions_called_first": None,
    }
    out["session1_repeat_rate"] = round(len(s1_pre) / len(s1), 4) if s1 else None
    out["session2_repeat_rate"] = round(len(s2_repeats) / len(s2), 4) if s2 else None
    if logs_dir is not None:
        f = Path(logs_dir) / "session2_commands.txt"
        if f.exists():
            cmds = [ln.strip() for ln in f.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
            cw = [c for c in cmds if re.search(r"\bcrosswalk(\.exe)?\b", c)]
            out["decisions_called_first"] = bool(cw) and re.search(r"\bdecisions\b", cw[0]) is not None
            out["session2_commands"] = len(cw)
    out["pass"] = (out["session2_repeats_of_session1_rejections"] == 0 and len(s1) > 0 and len(s2) > 0
                   and len(rejected) > 0 and out["decisions_called_first"] is not False)
    return out


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _fmt(x: Any, nd: int = 0) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return f"{x:,}" if isinstance(x, int) else str(x)


def render_md(res: dict) -> str:
    sc = res["setups"]
    use = res.get("usage") or {}
    cols = [l for l in "ABC"]
    L = ["# Agent comparison results", "",
         f"Questions: {res['questions']} golden questions, same model and prompts in all three setups. "
         f"Generated by `eval/score_agents.py`; transcripts in `eval/agent-runs/`.", ""]
    L += ["| KPI | A. Spreadsheet agent | B. Graph, no claim check | C. Graph + claim checker |", "|---|---|---|---|"]

    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(fn(sc.get(c)) if sc.get(c) else "not run" for c in cols) + " |")

    row("Answer accuracy (exact match)", lambda s: f"{s['correct']}/{s['questions']} ({_pct(s['accuracy'])})")
    row("Claims with a valid citation", lambda s: "n/a (no receipts)" if "valid_citation_rate" not in s
        else f"{s['valid_citations']}/{s['claims_total'] - s['aggregate_claims']} ({_pct(s['valid_citation_rate'])})")
    row("**Wrong claims shown to the user**", lambda s: f"{s['wrong_answers_shown']} wrong answers (claims have no paths)"
        if "wrong_claims_shown" not in s else f"{s['wrong_claims_shown']} wrong claims; {s['wrong_answers_shown']} wrong answers")
    row("Trap hits", lambda s: f"{s['trap_hits']}/{s['trap_questions']}")
    row("Tokens per question", lambda s: _per_q(use.get(s["setup"]), "tokens_total", s))
    row("Time per question (s)", lambda s: _per_q(use.get(s["setup"]), "seconds_total", s, 1))
    row("Tool calls per question", lambda s: _fmt(s["tool_calls_per_question"], 1))
    if sc.get("C") and sc["C"].get("draft_wrong_claims") is not None:
        L += ["", f"Claim checker on setup C: {sc['C']['draft_wrong_claims']} wrong claims in the drafts, "
                  f"{sc['C']['draft_wrong_claims_caught']} of them removed or flagged before the final answer."]
    L += ["", "Wrong claims shown (B, C) are cited paths that fail `crosswalk.claims` at the store's as_of: expired, only "
              "proposed, rejected, not adopted, fabricated. Setup A cites no paths, so its wrong answers are reported "
              "instead. Rules: `eval/score_agents.py` docstring.", ""]
    L += ["## Per-question grid", "", "`ok` = every scored key matches; `TRAP` = answer wrong in the planted trap's "
          "direction; `w` = wrong claims shown.", "",
          "| Question | Trap | A | B | C |", "|---|---|---|---|---|"]
    by_id = {c: {r["id"]: r for r in sc[c]["grid"]} for c in cols if sc.get(c)}
    for q in res["question_ids"]:
        cells = []
        for c in cols:
            r = by_id.get(c, {}).get(q["id"])
            if r is None:
                cells.append("-")
            elif not r["answered"]:
                cells.append("no answer")
            else:
                s = "ok" if r["correct"] else f"wrong ({', '.join(r.get('wrong_keys', [])[:3])})"
                if r["trap_hit"]:
                    s += " TRAP"
                if r.get("wrong_claims"):
                    s += f" w={r['wrong_claims']}"
                cells.append(s)
        L.append(f"| {q['id']} | {q.get('trap') or ''} | " + " | ".join(cells) + " |")
    rr = res.get("repeat_rejection")
    if rr:
        L += ["", "## Repeat-rejection (2-session run)", "",
              "| Metric | Value |", "|---|---|",
              f"| Session 1 proposals / rejected by script | {len(rr['session1_proposals'])} / {len(rr['session1_rejected'])} |",
              f"| Session 1 proposals that repeat a pre-existing rejection (baseline) | {rr['session1_repeats_of_preexisting_rejections']} |",
              f"| Session 2 proposals | {len(rr['session2_proposals'])} |",
              f"| **Session 2 proposals matching a session-1 rejection** (target 0) | {rr['session2_repeats_of_session1_rejections']} |",
              f"| of those, flagged by the verifier | {rr['session2_repeats_flagged_by_verifier']} |",
              f"| Session 2 called `crosswalk decisions` first | {_fmt(rr['decisions_called_first'])} |",
              f"| Result | {'PASS' if rr['pass'] else 'FAIL'} |"]
        for p in rr["session2_repeat_pairs"]:
            L.append(f"| repeat | {p['control']} -> {p['requirement']} |")
    L += ["", "Fictional company, one model, one question set, published transcripts. No claims beyond that.", ""]
    return "\n".join(L)


def _per_q(u: dict | None, key: str, s: dict, nd: int = 0) -> str:
    if not u or u.get(key) is None:
        return "n/a"
    n = max(s["answered"], 1)
    return _fmt(float(u[key]) / n, nd) if nd else f"{float(u[key]) / n:,.0f}"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def run(runs: Path = RUNS, usage: dict | None = None, store: str | Path = "data/crosswalk",
        out_dir: Path | None = OUT_DIR, repeat_store: str | Path | None = None, repeat_logs: Path | None = None,
        golden_path: Path = GOLDEN) -> dict:
    golden = load_golden(golden_path)
    present = {c for c, d in SETUPS.items() if (Path(runs) / d / "answers.jsonl").exists()}
    answers = {c: load_answers(Path(runs) / SETUPS[c] / "answers.jsonl") for c in present}
    conn = registry_factory = check_claims = None
    if present & {"B", "C"}:
        import relate

        from crosswalk.claims import PathRegistry, check_claims as cc

        conn = relate.connect(str(store), read_only=True)
        registry_factory, check_claims = PathRegistry, cc
    try:
        setups = {c: score_setup(c, answers[c], golden, conn, check_claims, registry_factory)
                  for c in "ABC" if c in present}
    finally:
        if conn is not None:
            conn.close()
    res: dict = {"questions": len(golden), "question_ids": [{"id": q["id"], "trap": q.get("trap")} for q in golden],
                 "setups": setups, "usage": usage or {}}
    if repeat_store:
        res["repeat_rejection"] = score_repeat(repeat_store, repeat_logs)
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (out_dir / "results.md").write_text(render_md(res), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default=str(RUNS), help="folder holding A-spreadsheet/, B-graph/, C-graph-checker/")
    ap.add_argument("--usage", help='usage.json: {"A-spreadsheet": {"tokens_total": N, "seconds_total": S}, ...}')
    ap.add_argument("--store", default="data/crosswalk", help="store the claims are checked against (read-only)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--repeat-store", help="temp store after the two repeat-rejection sessions")
    ap.add_argument("--repeat-logs", help="folder with session2_commands.txt")
    ap.add_argument("--write-protocol-files", action="store_true", help="write questions.jsonl and answer_template.jsonl")
    a = ap.parse_args(argv)
    if a.write_protocol_files:
        write_protocol_files(Path(a.out_dir))
        print(f"wrote {a.out_dir}/questions.jsonl and answer_template.jsonl")
        return 0
    usage = json.loads(Path(a.usage).read_text(encoding="utf-8-sig")) if a.usage else None
    res = run(Path(a.runs), usage, a.store, Path(a.out_dir), a.repeat_store,
              Path(a.repeat_logs) if a.repeat_logs else None)
    for c, s in res["setups"].items():
        extra = f", wrong claims {s['wrong_claims_shown']}" if "wrong_claims_shown" in s else ""
        print(f"{s['setup']}: {s['correct']}/{s['questions']} correct, trap hits {s['trap_hits']}{extra}")
    if "repeat_rejection" in res:
        r = res["repeat_rejection"]
        print(f"repeat-rejection: session-2 repeats {r['session2_repeats_of_session1_rejections']} "
              f"({'PASS' if r['pass'] else 'FAIL'})")
    print(f"wrote {Path(a.out_dir) / 'results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
