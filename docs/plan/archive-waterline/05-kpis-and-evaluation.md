# 05 · KPIs and evaluation

**Core claim:** *Waterline finds every real path to a critical PLC from the files a utility already has, offline. An agent that uses the graph gives correct, checked answers, where an agent reading raw files guesses.*

Each KPI backs part of this claim with a number.

## Where the correct answers come from

| Source | Gives us | How |
|---|---|---|
| **Planted problems** in the fictional plant | Known exposure paths, choke points, zone violations, stale rules, plus **decoys** that look risky but aren't reachable | Written by hand into `eval/ground_truth.yaml` before the queries are written, so we can't tune to the answer |
| **Advisory match labels** | Which plant assets each chosen CISA advisory really affects (product plus version range) | Labelled by hand for ~30 advisories |
| **Required flows** | Flows a fix must never break | `required_flows.yaml` |
| **Golden questions** for agents | 20 questions with exact expected answers | Expected answers are produced by our own queries, so they are deterministic |
| **Manual baseline** | Minutes to answer 5 questions by hand from the CSVs | We time ourselves and label the result clearly as an estimate |

## KPI table

### A. Detection correctness (backs "finds every real path")

| KPI | Definition | Target |
|---|---|---|
| Path recall | Planted exposure paths found / planted paths | **100%** |
| False alarms | Paths reported that aren't real (decoys flagged) | **0** |
| Zone-violation and stale-rule catch rate | Found / planted | 100% |
| Choke-point accuracy | Top choke point equals the planted one | Exact match |
| Advisory match precision and recall | Against the hand-labelled advisory set | ≥ 0.95 / 1.0 (missing one is worse than one extra) |

### B. Fix safety (backs "safer fixes")

| KPI | Definition | Target |
|---|---|---|
| Paths closed by top 3 fixes | Share of exposure paths removed by the 3 highest-ranked fixes | Report the number (e.g. "3 fixes close 100% of paths") |
| Required flows kept | Required flows still working after the recommended fixes | **20 / 20** |
| Bad-fix catch rate | Planted unsafe proposals (ones that break a required flow) caught by clone verification | **100%** |

### C. Agent reliability (backs "graph agent proves, raw-file agent guesses")

The same 20 golden questions, the same model, two setups:

| KPI | Agent + raw CSVs | Agent + Waterline graph (MCP) |
|---|---|---|
| Answer accuracy (exact match) | measured | measured. Target ≥ 90%, and better than the CSV agent |
| Answers backed by a checkable path | measured | target 100% |
| Tokens per question | measured | target clearly lower |
| Tool calls per question | measured | measured |
| Unsafe fixes proposed and **not** caught | measured | target 0 (clone verification) |

This needs a model API key, so judges can't re-run it for free. We **publish the transcripts** in `eval/agent-runs/`, the exact prompts, and a script that anyone with a key can re-run. The README says this clearly.

### D. User impact (backs "useful")

| KPI | Definition | How shown |
|---|---|---|
| Time to triage an advisory | Seconds for `waterline advisory <id>` vs. the timed manual baseline | Scorecard plus video |
| Time to answer "are we exposed?" | Seconds vs. the manual baseline | Scorecard |
| Exposure before and after | Paths to safety-critical processes: before vs. after the recommended fixes | Headline number, e.g. "3 → 0" |
| Hand-off ready | A report is generated with every path explained | Sample report in `eval/sample-report.md` |

### E. Offline, system and reproducibility (backs "works where cloud tools can't")

| KPI | Definition | Target |
|---|---|---|
| **Offline proof** | Full build, queries and scorecard pass in a container with **no network** | Pass (CI job) |
| Cold start to first path | Fresh clone → `waterline paths` following the README | ≤ 5 min on Windows and Linux |
| Build time | `waterline build` for the plant | ≤ 30 s |
| Query latency | p50 and p95 for Q1 to Q7 (warm) | p95 < 200 ms |
| What-if time | clone + change + re-check | < 2 s |
| Store size | `data/fernhollow.rl` | < 10 MB |
| Deterministic build | Two builds from the same inputs give the same content | No differences |
| Browser offline | `web/index.html` opens and works with no internet | Pass (manual check plus Playwright test) |

## How the KPIs are wired in

1. **One command:** `waterline scorecard` runs sections A, B, D and E against the committed file and the ground truth. It writes `eval/scorecard.json` and `eval/scorecard.md`.
2. **Tests equal truth.** Every planted problem and every decoy is its own pytest. "Path recall 100%, false alarms 0" is literally the suite passing.
3. **CI on every push:**
   - build
   - tests
   - scorecard
   - an **offline job** (container started without network)
   - the JSON-codec export
   - Pages deploy

   The run fails if any section A or B KPI regresses.
4. **README headline** (4 rows): paths found (3/3, 0 false alarms), fixes (3 → 0 paths, 20/20 flows kept), agent accuracy (graph vs. CSV), and "works fully offline ✔".
5. **Browser Scorecard tab** reads `scorecard.json`.
6. **Video:** a 15-second beat on the scorecard plus the agent comparison table.

## Honesty rules

- The plant is fictional. Say so wherever results appear.
- Manual baselines are labelled as estimates.
- The agent comparison is one model, one question set, published transcripts. No broad claims.
- If a target is missed, publish the real number and a short note.
- Waterline only sees what is in the files. A device missing from the inventory is invisible to it. This limit goes in the README.
