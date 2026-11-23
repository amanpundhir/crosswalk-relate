"""``crosswalk scorecard``: the KPIs of docs/plan/05 computed from the committed store, with no AI call.

Sections (same letters as the plan):

* D core correctness   Cypher answers (queries/*.cypher) compared with ``eval/ground_truth.json``
* C guardrails         claim checker on planted false claims, bad proposals, repeat rejection (recorded),
                       unauthorised writes, concurrency, live-catch replays
* B mapping quality    read from ``eval/mapping_scores.json``
* A agent reliability  read from ``eval/agent-runs/results-run*.json`` (recorded runs)
* E user impact        reuse ratio, inherited coverage, early-warning lead time, stale tracker rows
* F system             build time, query latency, claim-check time, store sizes (timings in their own block)

Everything except the ``timings`` block is deterministic.  Output: ``eval/scorecard.json`` and
``eval/scorecard.md``.  ``--quick`` skips the build timing, the concurrency demos and uses a single
live-catch replay.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import relate
import yaml

os.environ.setdefault("DO_NOT_TRACK", "1")

from crosswalk import build as B  # noqa: E402
from crosswalk import claims as C  # noqa: E402
from crosswalk import demo_live  # noqa: E402
from crosswalk import proposals as P  # noqa: E402
from crosswalk import queries as Q  # noqa: E402
from crosswalk.paths import make_path  # noqa: E402
from crosswalk.verify import verify  # noqa: E402

ROOT = B.REPO_ROOT
EVAL = ROOT / "eval"
OUT_JSON = EVAL / "scorecard.json"
OUT_MD = EVAL / "scorecard.md"
GT_PATH = EVAL / "ground_truth.json"
FRAMEWORKS = ["800-53", "800-171", "CSF"]
RUNS_LABEL = "recorded runs, Claude Sonnet 5.5 subagents, same prompts, same 20 golden questions"


# --------------------------------------------------------------------------
# metric helpers
# --------------------------------------------------------------------------


def metric(mid: str, name: str, value: Any, target: str, status: str, source: str, note: str | None = None) -> dict:
    m = {"id": mid, "name": name, "value": value, "target": target, "status": status, "source": source}
    if note:
        m["note"] = note
    return m


def ps(ok: bool) -> str:
    return "pass" if ok else "miss"


def frac(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({100 * n / d:.0f}%)" if d else "")


def _read_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _copy(store: Path) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="crosswalk-score-")) / "crosswalk"
    shutil.copytree(store, dest)
    return dest


def _count(conn, cypher: str) -> int:
    return conn.execute(cypher).fetchall()[0]["n"]


# --------------------------------------------------------------------------
# D core correctness
# --------------------------------------------------------------------------


def _ids(rows: list[dict], status: str) -> set[str]:
    return {r["id"] for r in rows if r["status"] == status}


def _blast_diff(res: dict, exp: dict) -> tuple[int, int, int]:
    """(checks passed, checks total, extra flagged items) comparing one blast result with the oracle."""
    checks = [
        ({e["evidence"] for e in res["expiring_evidence"]}, {e["evidence"] for e in exp["expiring_evidence"]}),
        (set(res["controls_left_without_valid_evidence"]), set(exp["controls_left_without_valid_evidence"])),
        ({b["requirement"] for b in res["broken_requirements"]}, {b["requirement"] for b in exp["broken_requirements"]}),
        (set(res["broken_and_not_inherited"]), set(exp["broken_and_not_inherited"])),
        ({a["audit"] for a in res["affected_audits"]}, {a["audit"] for a in exp["affected_audits"]}),
        (res["broken_counts"], exp["broken_counts"]),
    ]
    for fw in FRAMEWORKS:
        checks.append((set(res["broken_by_framework"].get(fw, [])), set(exp["broken_by_framework"].get(fw, []))))
    got_b = {b["requirement"]: b for b in res["broken_requirements"]}
    want_b = {b["requirement"]: b for b in exp["broken_requirements"]}
    for r, w in want_b.items():
        g = got_b.get(r)
        checks.append(((set(g["controls_lost"]), g["still_inherited"]) if g else None,
                       (set(w["controls_lost"]), w["still_inherited"])))
    ok = sum(a == b for a, b in checks)
    extra = len(({e["evidence"] for e in res["expiring_evidence"]} - {e["evidence"] for e in exp["expiring_evidence"]})
                | (set(got_b) - set(want_b)))
    return ok, len(checks), extra


def section_d(conn, gt: dict) -> list[dict]:
    out: list[dict] = []
    # planted-gap catch rate: every gap the oracle lists is a gap in Q1, and S1 is found by explain
    want_gaps = got_gaps = false_gaps = 0
    q1_exact = 0
    for fw in FRAMEWORKS:
        exp = gt["q1_coverage"]["by_framework"][fw]
        reqs = Q.coverage(conn, fw)["requirements"]
        gaps, wgaps = _ids(reqs, "gap"), set(exp["gap"])
        want_gaps += len(wgaps)
        got_gaps += len(gaps & wgaps)
        false_gaps += len(gaps - wgaps)
        q1_exact += (gaps == wgaps and _ids(reqs, "covered") == set(exp["covered_direct"])
                     and _ids(reqs, "inherited") == set(exp["inherited"]))
    s1 = Q.explain(conn, "800-171:03.05.03")
    s1_ok = (not s1["covered_direct"] and not s1["inherited"] and s1["proposed_only"] == ["CTRL-PWP-4"]
             and [p["evidence"] for p in s1["paths"]] == ["EV-044"] and not s1["paths"][0]["valid"])
    out.append(metric("D1", "Planted-gap catch rate (Q1 gaps vs oracle, 3 frameworks)", frac(got_gaps, want_gaps),
                      "100%", ps(got_gaps == want_gaps), "queries.coverage vs ground_truth.q1_coverage"))
    out.append(metric("D1b", "Live-catch scenario S1 found by explain (expired EV-044, PR-005 proposed only)", s1_ok,
                      "true", ps(s1_ok), "queries.explain(800-171:03.05.03)"))
    out.append(metric("D1c", "Q1 id-set exact match per framework", frac(q1_exact, len(FRAMEWORKS)), "all exact",
                      ps(q1_exact == len(FRAMEWORKS)), "covered/inherited/gap id sets"))
    # blast accuracy
    ok = tot = extra = 0
    scenarios = [(Q.blast(conn, days=30), gt["q3_blast_30d"])]
    scenarios += [(Q.blast(conn, audit=a), exp) for a, exp in sorted(gt["q3_blast_until_audit"].items())]
    for res, exp in scenarios:
        o, t, e = _blast_diff(res, exp)
        ok, tot, extra = ok + o, tot + t, extra + e
    out.append(metric("D2", "Blast-radius accuracy (Q3: 30-day window and every audit)", frac(ok, tot), "exact match",
                      ps(ok == tot), "queries.blast vs ground_truth.q3_*",
                      f"{len(scenarios)} scenarios; evidence, broken requirements, inherited flags, audits, counts"))
    # adopt accuracy
    a_ok = a_tot = 0
    for fw in ("800-171", "CSF"):
        exp, res = gt["q2_adopt"][fw], Q.adopt(conn, fw)
        got = {i["requirement"]: {v["neighbour"]: {c["control"]: set(c["evidence"]) for c in v["controls"]} for v in i["via"]}
               for i in res["inherited"]}
        want = {i["requirement"]: {v["neighbour"]: {c["control"]: set(c["evidence"]) for c in v["controls"]} for v in i["via"]}
                for i in exp["inherited"]}
        a_tot += 1
        a_ok += got == want and res["inherited_count"] == exp["inherited_count"]
    out.append(metric("D3", "Adopt accuracy (Q2: inherited set, neighbours, controls, evidence)", frac(a_ok, a_tot),
                      "exact match", ps(a_ok == a_tot), "queries.adopt vs ground_truth.q2_adopt"))
    # false alarms: anything flagged that is not planted
    stale = Q.stale(conn)
    want_stale = {s["control"] for s in gt["legacy_stale"]}
    stale_extra = set(stale["by_issue"].get("expired_evidence", [])) - want_stale
    blast_ids = {e["evidence"] for e in Q.blast(conn, audit="AUD-171")["expiring_evidence"]}
    decoys = {d["evidence"] for d in gt["decoys"]} & blast_ids
    n_false = false_gaps + extra + len(stale_extra) + len(decoys)
    out.append(metric("D4", "False alarms (flagged, not planted)", n_false, "0", ps(n_false == 0),
                      "extra gaps + extra blast items + stale rows outside legacy_stale + decoys flagged",
                      f"gaps {false_gaps}, blast {extra}, stale {len(stale_extra)}, decoys {len(decoys)}"))
    # explain exactness over all requirements
    exp_ok = 0
    for rid, exp in gt["explain"].items():
        res = Q.explain(conn, rid)
        exp_ok += (res["covered_direct"] == exp["covered_direct"] and res["inherited"] == exp["inherited"]
                   and set(res["proposed_only"]) == set(exp["proposed_only"]) and len(res["paths"]) == len(exp["paths"]))
    out.append(metric("D5", "Explain agrees with the oracle (every requirement)", frac(exp_ok, len(gt["explain"])),
                      "exact match", ps(exp_ok == len(gt["explain"])), "queries.explain vs ground_truth.explain"))
    return out


# --------------------------------------------------------------------------
# C guardrails
# --------------------------------------------------------------------------


def _crafted_claims(conn) -> tuple[list[dict], dict]:
    """(claims that are wrong and must NOT verify, a list of receipts for the answer)."""
    ex = Q.explain(conn, "800-171:03.05.03")
    expired = ex["paths"][0]
    proposed = ex["proposed_paths"][0]
    stale_path = None
    exp_ev = Q.run(conn, "stale_tracker", {"as_of": Q._as_of(conn, None)})
    for r in exp_ev:
        for e in r["evidence"]:
            if not e["valid"] and r["control"] == "CTRL-ASP-12":
                stale_path = make_path([f"Evidence:{e['evidence']}", f"Control:{r['control']}"], ["PROVES"])
                break
        if stale_path:
            break
    inline = [
        make_path(["Requirement:800-171:03.05.03", "Control:CTRL-AOTP-8", "Evidence:EV-065"], ["SATISFIES<-", "PROVES<-"]),
        make_path(["Requirement:800-171:03.05.03", "Control:CTRL-REAP-6"], ["SATISFIES<-"]),
    ]
    if stale_path:
        inline.append(stale_path)
    wrong = [
        ("expired evidence cited as coverage", {"text": "03.05.03 is covered by CTRL-REAP-6 via EV-044", "kind": "coverage",
                                                "path_ids": [expired["path_id"]]}),
        ("proposed mapping counted as covered", {"text": "03.05.03 is covered by CTRL-PWP-4", "kind": "coverage",
                                                  "path_ids": [proposed["id"]]}),
        ("fabricated path id", {"text": "03.05.03 is covered", "kind": "coverage", "path_ids": ["P-0123456789ab"]}),
        ("claim with no receipt", {"text": "MFA is covered", "kind": "coverage", "path_ids": []}),
        ("evidence that does not prove the control", {"text": "EV-065 proves CTRL-AOTP-8 for 03.05.03", "kind": "coverage",
                                                       "path_ids": [inline[0]["id"]]}),
        ("mapping with no evidence shown as coverage", {"text": "03.05.03 is covered by CTRL-REAP-6", "kind": "coverage",
                                                         "path_ids": [inline[1]["id"]]}),
    ]
    if stale_path:
        wrong.append(("tracker says Compliant, evidence expired", {"text": "CTRL-ASP-12 is evidenced", "kind": "coverage",
                                                                   "path_ids": [stale_path["id"]]}))
    return wrong, {"paths": inline}


def _good_claims(conn) -> list[dict]:
    row = next(r for r in Q.coverage(conn, "800-171")["requirements"] if r["status"] == "covered")
    p = row["paths"][0]
    return [{"text": f"{row['id']} is covered", "kind": "coverage", "path_ids": [p["id"]]}]


def section_c(store: Path, quick: bool, results: dict | None, timings: dict) -> list[dict]:
    out: list[dict] = []
    conn = relate.connect(str(store), read_only=True)
    try:
        wrong, extra = _crafted_claims(conn)
        t0 = time.perf_counter()
        checked = C.check_claims(conn, {"question": "crafted", "agent": "scorecard", **extra,
                                        "claims": [c for _, c in wrong] + _good_claims(conn)}, C.PathRegistry())
        timings["claim_check_ms_crafted"] = round((time.perf_counter() - t0) * 1000, 1)
        verdicts = [c["verdict"] for c in checked["claims"]]
        caught = sum(v != "verified" for v in verdicts[:len(wrong)])
        good_ok = verdicts[len(wrong):] == ["verified"] * (len(verdicts) - len(wrong))
        out.append(metric("C1", "Claim-checker catch rate, crafted wrong claims", frac(caught, len(wrong)), "100%",
                          ps(caught == len(wrong)), "claims.check_claims",
                          "; ".join(n for n, _ in wrong)))
        out.append(metric("C1b", "Claim checker passes a correct claim (no false alarm)", good_ok, "true", ps(good_ok),
                          "claims.check_claims"))
        # bad proposals
        bad = yaml.safe_load((EVAL / "bad_proposals.yaml").read_text(encoding="utf-8"))
        hit = [b["id"] for b in bad if (lambda r: not r["verified"] and r["reason_code"] == b["expected_reason"])(
            verify(conn, b["proposal"]))]
        out.append(metric("C2", "Bad-proposal catch rate (verify, expected reason code)", frac(len(hit), len(bad)), "100%",
                          ps(len(hit) == len(bad)), "eval/bad_proposals.yaml via verify.verify",
                          "missed: " + ", ".join(sorted({b['id'] for b in bad} - set(hit))) if len(hit) != len(bad) else None))
    finally:
        conn.close()
    # live catch replays
    n = 1 if quick else 10
    good = 0
    lat = []
    for _ in range(n):
        res = demo_live.run(store, draft=False)
        lat.append(res["latency_ms"])
        syms = [c["symbol"] for c in res["checked"]["claims"]]
        reasons = " ".join(r for c in res["checked"]["claims"] for r in c["reasons"])
        good += syms == ["✖", "⚠"] and "EV-044 expired 2026-12-01" in reasons and "PR-005" in reasons
    timings["live_catch_check_ms_p50"] = round(statistics.median(lat), 1)
    out.append(metric("C3", "Live-catch reproducibility (expired EV-044 + proposed-only PR-005)", f"{good}/{n} replays",
                      "10 / 10 replays", ps(good == n), "demo_live.run on a fresh temp copy each time",
                      "quick mode: 1 replay" if quick else None))
    # repeat rejection (recorded)
    rr = (results or {}).get("repeat_rejection")
    if rr:
        out.append(metric("C4", "Repeat-rejection rate, session 2 (recorded 2-session run)",
                          f"session 1: {rr['session1_repeat_rate']:.0%}, session 2: {rr['session2_repeat_rate']:.0%}",
                          "session 2: 0", ps(rr["session2_repeat_rate"] == 0 and rr["pass"]),
                          "eval/agent-runs/results-run2.json",
                          f"decisions consulted first: {rr['decisions_called_first']}; "
                          f"{rr['session2_repeats_flagged_by_verifier']} repeats reached the verifier"))
    # unauthorised writes: what the MCP propose tools call, on a temp copy
    work = _copy(store)
    try:
        w = P.open_writer(work)
        try:
            sat0 = _count(w, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n")
            dec0 = _count(w, "MATCH (d:Decision) RETURN count(d) AS n")
            impl0 = _count(w, "MATCH (c:Control) WHERE c.status = 'implemented' RETURN count(c) AS n")
            made = 0
            for b in bad:
                p = b["proposal"]
                kind = p.get("type")
                try:
                    if kind == "mapping":
                        P.create_proposal(w, "map", "scorecard-agent", p["control"], p["requirement"], p["rationale"])
                        made += 1
                except P.ProposalError:
                    pass
            P.create_proposal(w, "map", "scorecard-agent", "CTRL-PWP-4", "800-171:03.05.03", "scorecard probe",
                              status="approved")
            made += 1
            sat1 = _count(w, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n")
            dec1 = _count(w, "MATCH (d:Decision) RETURN count(d) AS n")
            impl1 = _count(w, "MATCH (c:Control) WHERE c.status = 'implemented' RETURN count(c) AS n")
        finally:
            w.close()
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)
    unauth = (sat1 - sat0) + (dec1 - dec0) + abs(impl1 - impl0)
    out.append(metric("C5", "Unauthorised writes (new SATISFIES / Decision / status change after propose tools)", unauth,
                      "0", ps(unauth == 0), "proposals.create_proposal on a temp copy",
                      f"{made} proposals written, all pending; also asserted by tests/test_mcp_server.py"))
    # concurrency
    if quick:
        out.append(metric("C6", "Concurrent-write integrity (lost updates / writes)", "skipped (--quick)", "0", "info",
                          "demo_concurrency"))
    else:
        from crosswalk import demo_concurrency as D
        lost = writes = 0
        modes = {}
        for mode, fn in (("embedded", D.run_embedded), ("server", D.run_server)):
            work = D._copy_store(store)
            try:
                r = fn(work, echo=False)
            except B.BuildError:
                # served mode needs the separate relate CLI (README, "Setup and run, With AI", step 2); the no-AI path has only
                # the Python package, so report the embedded half instead of failing the whole scorecard
                if mode != "server":
                    raise
                modes[mode] = "skipped (the relate CLI is not installed)"
                continue
            finally:
                shutil.rmtree(work.parent, ignore_errors=True)
            lost += r["lost_updates"]
            writes += 2
            modes[mode] = f"lost {r['lost_updates']}, conflicts retried {r['conflicts']}, lock refusals {r['lock_waits']}"
        both = "both modes" if writes == 4 else "embedded only"
        out.append(metric("C6", f"Concurrent-write integrity (lost updates / writes, {both})", f"{lost}/{writes}", "0",
                          ps(lost == 0), "demo_concurrency.run_embedded + run_server on temp copies",
                          "; ".join(f"{k}: {v}" for k, v in modes.items())))
    return out


# --------------------------------------------------------------------------
# B mapping quality, A agent reliability (recorded)
# --------------------------------------------------------------------------


def section_b() -> list[dict]:
    ms = _read_json(EVAL / "mapping_scores.json")
    if not ms:
        return [metric("B0", "Mapping scores", "missing", "n/a", "info", "eval/mapping_scores.json")]
    m = ms["methods"]
    out = []
    names = {"fulltext": "Full-text only", "vector": "Vector only", "hybrid": "Hybrid (WRRF)",
             "hybrid+graph": "Hybrid plus graph re-rank"}
    for i, (k, label) in enumerate(names.items(), 1):
        v = m[k]
        out.append(metric(f"B{i}", f"{label}: Precision@5 / Recall@10 / MRR",
                          f"{v['precision_at_5']:.3f} / {v['recall_at_10']:.3f} / {v['mrr']:.3f}", "measured", "info",
                          "eval/mapping_scores.json", f"{ms['controls']} hand-labelled controls, {ms['framework']}, leave-one-out"))
    best_single = max(m["fulltext"]["mrr"], m["vector"]["mrr"])
    out.append(metric("B5", "Hybrid MRR beats each single method", f"{m['hybrid']['mrr']:.3f} vs {best_single:.3f}",
                      "hybrid > both", ps(m["hybrid"]["mrr"] > best_single), "eval/mapping_scores.json"))
    out.append(metric("B6", "Graph re-rank MRR improves on hybrid", f"{m['hybrid+graph']['mrr']:.3f} vs {m['hybrid']['mrr']:.3f}",
                      "re-rank > hybrid", ps(m["hybrid+graph"]["mrr"] > m["hybrid"]["mrr"]), "eval/mapping_scores.json"))
    out.append(metric("B7", "Mapper agent row", "not measured", "improves on hybrid", "info", "n/a",
                      "needs a model key; not part of mapping_scores.json"))
    return out


def section_a(run2: dict | None, run1: dict | None) -> tuple[list[dict], dict]:
    if not run2:
        return [metric("A0", "Agent runs", "missing", "n/a", "info", "eval/agent-runs/results-run2.json")], {}
    s = run2["setups"]
    a, b, c = s["A"], s["B"], s["C"]
    src = "eval/agent-runs/results-run2.json"
    lab = RUNS_LABEL
    out = [
        metric("A1", "Answer accuracy, spreadsheet agent", frac(a["correct"], a["questions"]), "measured", "info", src),
        metric("A2", "Answer accuracy, graph agent without claim check", frac(b["correct"], b["questions"]), "measured", "info", src),
        metric("A3", "Answer accuracy, graph agent + claim checker", frac(c["correct"], c["questions"]), ">= 90%",
               ps(c["accuracy"] >= 0.9), src),
        metric("A4", "Claims with a valid citation, graph + checker", f"{c['valid_citations']}/{c['cited_claims']}",
               "100% of shown claims", ps(c["valid_citation_rate"] == 1.0), src),
        metric("A4b", "Claims with a valid citation, graph without checker", f"{b['valid_citations']}/{b['cited_claims']}",
               "measured", "info", src),
        metric("A5", "Wrong claims shown, graph + checker (without checker: %d)" % b["wrong_claims_shown"],
               c["wrong_claims_shown"], "0", ps(c["wrong_claims_shown"] == 0), src,
               f"the checker flagged {c['draft_wrong_claims_caught']}/{c['draft_wrong_claims']} wrong draft claims; "
               f"wrong ANSWERS still shown with checker: {c['wrong_answers_shown']}"),
        metric("A5b", "Wrong answers shown, spreadsheet agent", a["wrong_answers_shown"], "measured", "info", src,
               f"spreadsheet answers carry no citations, so wrong claims cannot be checked"),
        metric("A6", "Trap hits, graph + checker (spreadsheet: %d, graph only: %d)" % (a["trap_hits"], b["trap_hits"]),
               c["trap_hits"], "0", ps(c["trap_hits"] == 0), src),
        metric("A7", "Tool calls per question (A / B / C)",
               f"{a['tool_calls_per_question']} / {b['tool_calls_per_question']} / {c['tool_calls_per_question']}",
               "measured", "info", src),
        metric("A8", "Tokens per question (A / B / C)",
               " / ".join(f"{run2['usage'][k]['tokens_total'] / run2['questions']:.0f}"
                          for k in ("A-spreadsheet", "B-graph", "C-graph-checker")), "measured", "info", src),
    ]
    history = {}
    if run1:
        r = run1["setups"]
        history = {"run1": {k: {"accuracy": r[k]["accuracy"], "wrong_claims_shown": r[k].get("wrong_claims_shown"),
                                "wrong_answers_shown": r[k]["wrong_answers_shown"], "trap_hits": r[k]["trap_hits"]}
                            for k in ("A", "B", "C")},
                   "run2": {k: {"accuracy": s[k]["accuracy"], "wrong_claims_shown": s[k].get("wrong_claims_shown"),
                                "wrong_answers_shown": s[k]["wrong_answers_shown"], "trap_hits": s[k]["trap_hits"]}
                            for k in ("A", "B", "C")},
                   "label": lab, "note": "run1 was the first attempt; prompts were tightened for run2"}
    return out, history


# --------------------------------------------------------------------------
# E user impact
# --------------------------------------------------------------------------


def section_e(conn) -> tuple[list[dict], dict]:
    out: list[dict] = []
    facts: dict[str, Any] = {}
    as_of = Q._as_of(conn, None)
    reuse = [r for r in Q.reuse(conn) if not r["expires_at"] or r["expires_at"] > as_of]
    counts = [r["direct_count"] for r in reuse]
    mean = statistics.mean(counts)
    best = max(reuse, key=lambda r: (r["direct_count"], r["evidence"]))
    multi = sum(1 for r in reuse if r["framework_count"] >= 2)
    facts["reuse_ratio"] = round(mean, 2)
    out.append(metric("E1", "Evidence reuse ratio (mean distinct requirements per valid evidence item)", round(mean, 2),
                      "measured (README headline)", "info", "queries.reuse",
                      f"{len(reuse)} valid items; median {statistics.median(counts)}; max {best['direct_count']} ({best['evidence']}, "
                      f"{best['framework_count']} frameworks); mean incl. one crosswalk hop "
                      f"{statistics.mean(r['reach_count'] for r in reuse):.2f}"))
    out.append(metric("E2", "Evidence items serving 2+ frameworks (one collection answers several audits)",
                      frac(multi, len(reuse)), "measured", "info", "queries.reuse",
                      f"{sum(r['framework_count'] - 1 for r in reuse)} duplicate collections avoided across frameworks"))
    for fw in ("800-171", "CSF"):
        a = Q.adopt(conn, fw)
        out.append(metric(f"E3-{fw}", f"Inherited coverage of {fw} (met through the crosswalk before any new work)",
                          frac(a["inherited_count"], a["active_requirements"]), "measured (adopt output)", "info",
                          "queries.adopt"))
    b = Q.blast(conn, audit="AUD-171")
    first = min(b["affected_audits"], key=lambda x: x["days_after_as_of"])
    soonest = min(e["expires_at"] for e in b["expiring_evidence"])
    import datetime as dt
    days_to_expiry = (dt.date.fromisoformat(soonest) - dt.date.fromisoformat(as_of)).days
    out.append(metric("E4", "Early-warning lead time (days from as_of to the first affected audit)",
                      first["days_after_as_of"], "measured", "info", "queries.blast(audit=AUD-171)",
                      f"{first['audit']} on {first['date']}; first expiry {soonest} is {days_to_expiry} days out, "
                      f"{first['days_after_as_of'] - days_to_expiry} days before that audit"))
    st = Q.stale(conn)
    out.append(metric("E5", "Stale tracker rows contradicted by the graph",
                      f"{st['stale_count']} of {st['marked_compliant']} marked Compliant", "measured", "info",
                      "queries.stale", f"{len(st['no_valid_evidence'])} have only expired evidence ("
                      + ", ".join(st["by_issue"].get("expired_evidence", [])) + "); the rest: "
                      + ", ".join(sorted(set(c for v in st["by_issue"].values() for c in v)
                                         - set(st["by_issue"].get("expired_evidence", []))))))
    return out, facts


# --------------------------------------------------------------------------
# F system
# --------------------------------------------------------------------------


def _pctl(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def section_f(store: Path, quick: bool) -> tuple[list[dict], dict]:
    sysm: list[dict] = []
    timings: dict[str, Any] = {}
    size = B.store_size(store) / 1e6
    sysm.append(metric("F1", "Store size (data/crosswalk)", f"{size:.2f} MB", "< 25 MB", ps(size < 25), "build.store_size"))
    gc = ROOT / "web" / "data" / "graph.cypher"
    if gc.exists():
        sysm.append(metric("F2", "Browser graph.cypher size", f"{gc.stat().st_size / 1e6:.2f} MB", "measured", "info",
                           "web/data/graph.cypher"))
    conn = relate.connect(str(store), read_only=True)
    try:
        cases: dict[str, Callable[[], Any]] = {
            "coverage 800-171": lambda: Q.coverage(conn, "800-171"),
            "adopt 800-171": lambda: Q.adopt(conn, "800-171"),
            "blast AUD-171": lambda: Q.blast(conn, audit="AUD-171"),
            "reuse": lambda: Q.reuse(conn),
            "owners": lambda: Q.owner_risk(conn),
            "explain 03.05.03": lambda: Q.explain(conn, "800-171:03.05.03"),
            "stale": lambda: Q.stale(conn),
        }
        p = Q.explain(conn, "800-171:03.05.03")["paths"][0]
        cases["check_path"] = lambda: Q.check_path(conn, p["nodes"], p["rels"])
        q: dict[str, dict] = {}
        for name, fn in cases.items():
            fn()  # warm up
            ts = []
            for _ in range(20):
                t0 = time.perf_counter()
                fn()
                ts.append((time.perf_counter() - t0) * 1000)
            q[name] = {"p50_ms": round(statistics.median(ts), 1), "p95_ms": round(_pctl(ts, 0.95), 1)}
        timings["query_latency"] = q
        worst = max(v["p95_ms"] for v in q.values())
        timings["query_p95_worst_ms"] = worst
        res = demo_live.run(store, draft=False)
        timings["claim_check_ms_live_catch"] = round(res["latency_ms"], 1)
    finally:
        conn.close()
    if not quick:
        tmp = Path(tempfile.mkdtemp(prefix="crosswalk-score-build-"))
        try:
            t0 = time.perf_counter()
            B.build(tmp / "crosswalk", export=False)
            timings["build_s"] = round(time.perf_counter() - t0, 1)
        except B.BuildError as exc:
            if "relate CLI was not found" not in str(exc):
                raise
            timings["build_skipped"] = "the relate CLI is not installed"  # a fresh build initialises the store with it
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return sysm, timings


def timing_metrics(t: dict, quick: bool) -> list[dict]:
    out = []
    if "build_s" in t:
        out.append(metric("F3", "crosswalk build time (embeddings cached)", f"{t['build_s']} s", "<= 60 s",
                          ps(t["build_s"] <= 60), "build.build into a temp dir"))
    elif quick:
        out.append(metric("F3", "crosswalk build time", "skipped (--quick)", "<= 60 s", "info", "build.build"))
    elif "build_skipped" in t:
        out.append(metric("F3", "crosswalk build time", f"skipped ({t['build_skipped']})", "<= 60 s", "info",
                          "build.build"))
    worst = t["query_p95_worst_ms"]
    out.append(metric("F4", "Query latency p95, worst of the core queries", f"{worst} ms", "< 200 ms", ps(worst < 200),
                      "20 runs per query after one warm-up", "per query in timings.query_latency"))
    cc = max(t["claim_check_ms_live_catch"], t["claim_check_ms_crafted"])
    out.append(metric("F5", "Claim-check time per answer", f"{cc} ms", "< 500 ms", ps(cc < 500), "claims.check_claims",
                      "worst case: crafted answer on a cold path registry (a fabricated id forces full path discovery)"))
    return out


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

TITLES = {
    "D": "D. Core correctness (Cypher vs ground truth, no AI)",
    "C": "C. Guardrails",
    "B": "B. Mapping quality (hand-labelled 800-53 targets)",
    "A": "A. Agent reliability (" + RUNS_LABEL + ")",
    "E": "E. User impact",
    "F": "F. System",
}


def _find(metrics: list[dict], mid: str) -> dict:
    return next(m for m in metrics if m["id"] == mid)


def build_scorecard(store: str | Path = "data/crosswalk", quick: bool = False) -> dict:
    store_p = B.resolve_store(store)
    if not (store_p / "manifest.json").exists():
        raise FileNotFoundError(f"no store at {store_p}; run `crosswalk build` first")
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    run2 = _read_json(EVAL / "agent-runs" / "results-run2.json")
    run1 = _read_json(EVAL / "agent-runs" / "results-run1.json")
    timings: dict[str, Any] = {}
    conn = relate.connect(str(store_p), read_only=True)
    try:
        as_of = Q._as_of(conn, None)
        d = section_d(conn, gt)
        e, facts = section_e(conn)
    finally:
        conn.close()
    c = section_c(store_p, quick, run2, timings)
    b = section_b()
    a, history = section_a(run2, run1)
    f, t2 = section_f(store_p, quick)
    timings.update(t2)
    f += timing_metrics(timings, quick)
    sections = {"D": d, "C": c, "B": b, "A": a, "E": e, "F": f}

    # headline block
    A1, A3 = _find(a, "A1")["value"], _find(a, "A3")["value"]
    wrong_b = run2["setups"]["B"]["wrong_claims_shown"] if run2 else None
    e1 = _find(e, "E1")
    live = _find(c, "C3")
    headline = [
        {"row": "Agent accuracy, spreadsheet vs graph + claim checker", "value": f"{A1} -> {A3}",
         "note": RUNS_LABEL},
        {"row": "Wrong claims shown to the user (graph agent without checker -> with checker)",
         "value": f"{wrong_b} -> {run2['setups']['C']['wrong_claims_shown']}" if run2 else "n/a",
         "note": f"spreadsheet agent: {run2['setups']['A']['wrong_answers_shown']} wrong answers shown, no citations to check"
         if run2 else ""},
        {"row": "Evidence reuse ratio", "value": f"{e1['value']} requirements per evidence item (mean)",
         "note": e1.get("note", "")},
        {"row": "Live catch caught", "value": f"{'yes' if live['status'] == 'pass' else 'NO'} ({live['value']})",
         "note": "expired EV-044 and the proposed-only mapping PR-005 flagged with reasons"},
    ]
    allm = [m for s in sections.values() for m in s]
    return {
        "title": "Crosswalk scorecard",
        "as_of": as_of,
        "mode": "quick" if quick else "full",
        "note": "Company data is fictional. Sections A and the repeat-rejection metric are read from recorded agent "
                "runs; everything else is computed now from the store with no AI call. Timings are the only "
                "non-deterministic numbers and live in the timings block.",
        "headline": headline,
        "summary": {"pass": sum(m["status"] == "pass" for m in allm), "miss": sum(m["status"] == "miss" for m in allm),
                    "info": sum(m["status"] == "info" for m in allm),
                    "misses": [m["id"] for m in allm if m["status"] == "miss"]},
        "sections": [{"id": k, "title": TITLES[k], "metrics": sections[k]} for k in "DCBAEF"],
        "agent_run_history": history,
        "timings": timings,
    }


def _v(v: Any) -> str:
    return {True: "yes", False: "no"}.get(v, v) if isinstance(v, bool) else str(v)


def _n(v: Any) -> str:
    return "n/a" if v is None else str(v)


def render_markdown(sc: dict) -> str:
    L = [f"# {sc['title']}", "", f"as_of {sc['as_of']} - mode: {sc['mode']}", "", sc["note"], "",
         "## Headline", "", "| Metric | Result | Note |", "|---|---|---|"]
    for h in sc["headline"]:
        L.append(f"| {h['row']} | **{h['value']}** | {h['note']} |")
    s = sc["summary"]
    L += ["", f"Pass {s['pass']}, miss {s['miss']}, info {s['info']}" + (f" (missed: {', '.join(s['misses'])})" if s["misses"] else ""), ""]
    for sec in sc["sections"]:
        L += [f"## {sec['title']}", "", "| ID | Metric | Value | Target | Status | Source |", "|---|---|---|---|---|---|"]
        for m in sec["metrics"]:
            L.append(f"| {m['id']} | {m['name']} | {_v(m['value'])} | {m['target']} | {m['status']} | {m['source']} |")
        notes = [f"- {m['id']}: {m['note']}" for m in sec["metrics"] if m.get("note")]
        if notes:
            L += ["", *notes]
        L.append("")
    hist = sc.get("agent_run_history")
    if hist:
        L += ["## Agent run history", "", f"{hist['note']} ({hist['label']})", "",
              "| Setup | Run 1 accuracy | Run 1 wrong claims / answers | Run 2 accuracy | Run 2 wrong claims / answers |",
              "|---|---|---|---|---|"]
        for k, name in (("A", "Spreadsheet"), ("B", "Graph"), ("C", "Graph + checker")):
            r1, r2 = hist["run1"][k], hist["run2"][k]
            L.append(f"| {name} | {r1['accuracy']:.0%} | {_n(r1['wrong_claims_shown'])} / {r1['wrong_answers_shown']} | "
                     f"{r2['accuracy']:.0%} | {_n(r2['wrong_claims_shown'])} / {r2['wrong_answers_shown']} |")
        L.append("")
    t = sc["timings"]
    L += ["## Timings (machine dependent, not deterministic)", "", "| Query | p50 ms | p95 ms |", "|---|---|---|"]
    for k, v in t["query_latency"].items():
        L.append(f"| {k} | {v['p50_ms']} | {v['p95_ms']} |")
    other = {k: v for k, v in t.items() if k != "query_latency"}
    L += ["", *[f"- {k}: {v}" for k, v in other.items()], ""]
    return "\n".join(L)


def run(store: str | Path = "data/crosswalk", quick: bool = False, write: bool = True) -> dict:
    sc = build_scorecard(store, quick)
    if write:
        OUT_JSON.write_text(json.dumps(sc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        OUT_MD.write_text(render_markdown(sc), encoding="utf-8")
    return sc
