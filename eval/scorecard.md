# Crosswalk scorecard

as_of 2026-12-02 - mode: full

Company data is fictional. Sections A and the repeat-rejection metric are read from recorded agent runs; everything else is computed now from the store with no AI call. Timings are the only non-deterministic numbers and live in the timings block.

## Headline

| Metric | Result | Note |
|---|---|---|
| Agent accuracy, spreadsheet vs graph + claim checker | **9/20 (45%) -> 19/20 (95%)** | recorded runs, Claude Sonnet 5.5 subagents, same prompts, same 20 golden questions |
| Wrong claims shown to the user (graph agent without checker -> with checker) | **3 -> 0** | spreadsheet agent: 11 wrong answers shown, no citations to check |
| Evidence reuse ratio | **2.15 requirements per evidence item (mean)** | 108 valid items; median 2.0; max 9 (EV-065, 3 frameworks); mean incl. one crosswalk hop 8.71 |
| Live catch caught | **yes (10/10 replays)** | expired EV-044 and the proposed-only mapping PR-005 flagged with reasons |

Pass 24, miss 0, info 18

## D. Core correctness (Cypher vs ground truth, no AI)

| ID | Metric | Value | Target | Status | Source |
|---|---|---|---|---|---|
| D1 | Planted-gap catch rate (Q1 gaps vs oracle, 3 frameworks) | 1041/1041 (100%) | 100% | pass | queries.coverage vs ground_truth.q1_coverage |
| D1b | Live-catch scenario S1 found by explain (expired EV-044, PR-005 proposed only) | yes | true | pass | queries.explain(800-171:03.05.03) |
| D1c | Q1 id-set exact match per framework | 3/3 (100%) | all exact | pass | covered/inherited/gap id sets |
| D2 | Blast-radius accuracy (Q3: 30-day window and every audit) | 87/87 (100%) | exact match | pass | queries.blast vs ground_truth.q3_* |
| D3 | Adopt accuracy (Q2: inherited set, neighbours, controls, evidence) | 2/2 (100%) | exact match | pass | queries.adopt vs ground_truth.q2_adopt |
| D4 | False alarms (flagged, not planted) | 0 | 0 | pass | extra gaps + extra blast items + stale rows outside legacy_stale + decoys flagged |
| D5 | Explain agrees with the oracle (every requirement) | 154/154 (100%) | exact match | pass | queries.explain vs ground_truth.explain |

- D2: 4 scenarios; evidence, broken requirements, inherited flags, audits, counts
- D4: gaps 0, blast 0, stale 0, decoys 0

## C. Guardrails

| ID | Metric | Value | Target | Status | Source |
|---|---|---|---|---|---|
| C1 | Claim-checker catch rate, crafted wrong claims | 7/7 (100%) | 100% | pass | claims.check_claims |
| C1b | Claim checker passes a correct claim (no false alarm) | yes | true | pass | claims.check_claims |
| C2 | Bad-proposal catch rate (verify, expected reason code) | 8/8 (100%) | 100% | pass | eval/bad_proposals.yaml via verify.verify |
| C3 | Live-catch reproducibility (expired EV-044 + proposed-only PR-005) | 10/10 replays | 10 / 10 replays | pass | demo_live.run on a fresh temp copy each time |
| C4 | Repeat-rejection rate, session 2 (recorded 2-session run) | session 1: 0%, session 2: 0% | session 2: 0 | pass | eval/agent-runs/results-run2.json |
| C5 | Unauthorised writes (new SATISFIES / Decision / status change after propose tools) | 0 | 0 | pass | proposals.create_proposal on a temp copy |
| C6 | Concurrent-write integrity (lost updates / writes, both modes) | 0/4 | 0 | pass | demo_concurrency.run_embedded + run_server on temp copies |

- C1: expired evidence cited as coverage; proposed mapping counted as covered; fabricated path id; claim with no receipt; evidence that does not prove the control; mapping with no evidence shown as coverage; tracker says Compliant, evidence expired
- C4: decisions consulted first: True; 0 repeats reached the verifier
- C5: 7 proposals written, all pending; also asserted by tests/test_mcp_server.py
- C6: embedded: lost 0, conflicts retried 0, lock refusals 11; server: lost 0, conflicts retried 1, lock refusals 0

## B. Mapping quality (hand-labelled 800-53 targets)

| ID | Metric | Value | Target | Status | Source |
|---|---|---|---|---|---|
| B1 | Full-text only: Precision@5 / Recall@10 / MRR | 0.165 / 0.433 / 0.418 | measured | info | eval/mapping_scores.json |
| B2 | Vector only: Precision@5 / Recall@10 / MRR | 0.175 / 0.479 / 0.495 | measured | info | eval/mapping_scores.json |
| B3 | Hybrid (WRRF): Precision@5 / Recall@10 / MRR | 0.195 / 0.542 / 0.554 | measured | info | eval/mapping_scores.json |
| B4 | Hybrid plus graph re-rank: Precision@5 / Recall@10 / MRR | 0.195 / 0.562 / 0.573 | measured | info | eval/mapping_scores.json |
| B5 | Hybrid MRR beats each single method | 0.554 vs 0.495 | hybrid > both | pass | eval/mapping_scores.json |
| B6 | Graph re-rank MRR improves on hybrid | 0.573 vs 0.554 | re-rank > hybrid | pass | eval/mapping_scores.json |
| B7 | Mapper agent row | not measured | improves on hybrid | info | n/a |

- B1: 40 hand-labelled controls, 800-53, leave-one-out
- B2: 40 hand-labelled controls, 800-53, leave-one-out
- B3: 40 hand-labelled controls, 800-53, leave-one-out
- B4: 40 hand-labelled controls, 800-53, leave-one-out
- B7: needs a model key; not part of mapping_scores.json

## A. Agent reliability (recorded runs, Claude Sonnet 5.5 subagents, same prompts, same 20 golden questions)

| ID | Metric | Value | Target | Status | Source |
|---|---|---|---|---|---|
| A1 | Answer accuracy, spreadsheet agent | 9/20 (45%) | measured | info | eval/agent-runs/results-run2.json |
| A2 | Answer accuracy, graph agent without claim check | 19/20 (95%) | measured | info | eval/agent-runs/results-run2.json |
| A3 | Answer accuracy, graph agent + claim checker | 19/20 (95%) | >= 90% | pass | eval/agent-runs/results-run2.json |
| A4 | Claims with a valid citation, graph + checker | 109/109 | 100% of shown claims | pass | eval/agent-runs/results-run2.json |
| A4b | Claims with a valid citation, graph without checker | 69/72 | measured | info | eval/agent-runs/results-run2.json |
| A5 | Wrong claims shown, graph + checker (without checker: 3) | 0 | 0 | pass | eval/agent-runs/results-run2.json |
| A5b | Wrong answers shown, spreadsheet agent | 11 | measured | info | eval/agent-runs/results-run2.json |
| A6 | Trap hits, graph + checker (spreadsheet: 6, graph only: 0) | 0 | 0 | pass | eval/agent-runs/results-run2.json |
| A7 | Tool calls per question (A / B / C) | 2.0 / 1.2 / 2.5 | measured | info | eval/agent-runs/results-run2.json |
| A8 | Tokens per question (A / B / C) | 4632 / 5162 / 5562 | measured | info | eval/agent-runs/results-run2.json |

- A5: the checker flagged 13/13 wrong draft claims; wrong ANSWERS still shown with checker: 1
- A5b: spreadsheet answers carry no citations, so wrong claims cannot be checked

## E. User impact

| ID | Metric | Value | Target | Status | Source |
|---|---|---|---|---|---|
| E1 | Evidence reuse ratio (mean distinct requirements per valid evidence item) | 2.15 | measured (README headline) | info | queries.reuse |
| E2 | Evidence items serving 2+ frameworks (one collection answers several audits) | 105/108 (97%) | measured | info | queries.reuse |
| E3-800-171 | Inherited coverage of 800-171 (met through the crosswalk before any new work) | 23/97 (24%) | measured (adopt output) | info | queries.adopt |
| E3-CSF | Inherited coverage of CSF (met through the crosswalk before any new work) | 81/106 (76%) | measured (adopt output) | info | queries.adopt |
| E4 | Early-warning lead time (days from as_of to the first affected audit) | 44 | measured | info | queries.blast(audit=AUD-171) |
| E5 | Stale tracker rows contradicted by the graph | 5 of 46 marked Compliant | measured | info | queries.stale |

- E1: 108 valid items; median 2.0; max 9 (EV-065, 3 frameworks); mean incl. one crosswalk hop 8.71
- E2: 186 duplicate collections avoided across frameworks
- E4: AUD-171 on 2027-01-15; first expiry 2026-12-18 is 16 days out, 28 days before that audit
- E5: 4 have only expired evidence (CTRL-ASP-12, CTRL-BCP-4, CTRL-REAP-3, CTRL-REAP-6); the rest: CTRL-MCP-13

## F. System

| ID | Metric | Value | Target | Status | Source |
|---|---|---|---|---|---|
| F1 | Store size (data/crosswalk) | 5.93 MB | < 25 MB | pass | build.store_size |
| F2 | Browser graph.cypher size | 0.62 MB | measured | info | web/data/graph.cypher |
| F3 | crosswalk build time (embeddings cached) | 2.5 s | <= 60 s | pass | build.build into a temp dir |
| F4 | Query latency p95, worst of the core queries | 48.6 ms | < 200 ms | pass | 20 runs per query after one warm-up |
| F5 | Claim-check time per answer | 438.8 ms | < 500 ms | pass | claims.check_claims |

- F4: per query in timings.query_latency
- F5: worst case: crafted answer on a cold path registry (a fabricated id forces full path discovery)

## Agent run history

run1 was the first attempt; prompts were tightened for run2 (recorded runs, Claude Sonnet 5.5 subagents, same prompts, same 20 golden questions)

| Setup | Run 1 accuracy | Run 1 wrong claims / answers | Run 2 accuracy | Run 2 wrong claims / answers |
|---|---|---|---|---|
| Spreadsheet | 45% | n/a / 11 | 45% | n/a / 11 |
| Graph | 85% | 5 / 3 | 95% | 3 / 1 |
| Graph + checker | 80% | 0 / 4 | 95% | 0 / 1 |

## Timings (machine dependent, not deterministic)

| Query | p50 ms | p95 ms |
|---|---|---|
| coverage 800-171 | 20.6 | 24.3 |
| adopt 800-171 | 9.2 | 10.6 |
| blast AUD-171 | 15.4 | 17.1 |
| reuse | 42.9 | 48.6 |
| owners | 41.5 | 46.2 |
| explain 03.05.03 | 1.5 | 1.7 |
| stale | 30.7 | 35.1 |
| check_path | 4.4 | 5.8 |

- claim_check_ms_crafted: 438.8
- live_catch_check_ms_p50: 9.6
- query_p95_worst_ms: 48.6
- claim_check_ms_live_catch: 10.3
- build_s: 2.5
