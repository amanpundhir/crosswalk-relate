# 05 · KPIs and evaluation

The core claim: **a graph lets a small team prove controls once, reuse them across frameworks, and catch audit risk early, and the mapping suggestions are good enough to trust with a review step.** Each KPI below backs part of that claim with a number.

## How we get ground truth

| Source | Gives us | How |
|--------|----------|-----|
| **NIST official crosswalk** (CSF 2.0 ↔ 800-53, 800-171 ↔ 800-53) | The correct mappings between real requirements | Hold out the official edges. Run our suggest engine from one framework's text to the other's. Compare. |
| **Planted scenarios** in the fictional company pack | Known answers to the six core questions | We hand-write the facts, for example "EV-044 expires Dec 30 and is the only proof for CTRL-007". Expected results live in `eval/ground_truth.yaml`. |
| **Golden question set** for agents | 20 natural-language questions with exact expected answers | Expected answers are computed by our own Cypher, so they are deterministic. |
| **Manual baseline timing** | "Before" time for each question | Time ourselves answering 5 questions from a spreadsheet export of the same data. Report it honestly as an estimate. |

## KPI table

### A. Retrieval quality (backs "suggestions are trustworthy")

| KPI | Definition | Target | Measured by |
|-----|------------|--------|-------------|
| Precision@5 | Share of the top 5 suggestions that are official mappings | ≥ 0.50 | `crosswalk scorecard` |
| Recall@10 | Share of official mappings found in the top 10 | ≥ 0.70 | Same |
| MRR | Mean reciprocal rank of the first correct mapping | ≥ 0.55 | Same |
| **Ablation** | The three KPIs for full text only, vector only and **hybrid**, side by side | Hybrid beats both | Same. This is the headline chart. |
| Graph boost | The same KPIs when candidates are re-ranked using graph context (for example, a family already mapped by sibling requirements) | Better than hybrid alone | Same. It shows that connected context helps. |

Targets are first guesses. We publish whatever the real numbers are, and the README says so.

### B. Correctness of the core questions (backs "it works")

| KPI | Definition | Target |
|-----|------------|--------|
| Planted-gap catch rate | Planted gaps found by Q1 / planted gaps | 100% |
| Blast-radius accuracy | Q3 output equals the expected set of controls, requirements and audits | Exact match |
| Adopt accuracy | Q2 output equals the expected inherited requirements | Exact match |
| False alarms | Items flagged that were not planted | 0 |
| Agent golden-question accuracy | Correct agent answers over MCP / 20 | ≥ 85%, run by hand and recorded in the video and the scorecard |

### C. User impact (backs "useful")

| KPI | Definition | How shown |
|-----|------------|-----------|
| **Evidence reuse ratio** | Distinct requirements satisfied per evidence item, across all frameworks | Scorecard plus README headline, for example "each evidence item satisfies 6.3 requirements across 3 frameworks" |
| Duplicate collections avoided | Evidence requests across audits that the same evidence item already covers | Scorecard |
| Inherited coverage | Share of a new framework met through the crosswalk before any new work | `adopt` output, for example "62% of 800-171 met on day 0" |
| Early warning lead time | Days between the blast alert and the first affected audit date | Scorecard |
| Time to answer | Seconds per core question (measured) versus the manual baseline (estimated minutes) | Scorecard plus video |

### D. System and reproducibility (backs "judges can run it")

| KPI | Definition | Target |
|-----|------------|--------|
| Cold start to first result | Fresh clone to `crosswalk coverage` output, following the README | ≤ 5 minutes, timed on Windows and Linux |
| Build time | `crosswalk build` from raw inputs (embeddings cached) | ≤ 60 s |
| Query latency | p50 and p95 per core question (Python, warm) | p95 < 200 ms |
| Browser load | Time until the WASM explorer is interactive | < 3 s on a laptop |
| Store size | `data/crosswalk/` on disk | < 25 MB |
| Deterministic build | Two builds from the same inputs give a store with the same content | Diff is empty |

## How the KPIs are integrated

1. **One command:** `crosswalk scorecard` runs all of A, B and D (and C where it can be computed) against the committed store and the ground truth. It writes `eval/scorecard.json` (machine-readable) and `eval/scorecard.md` (human-readable).
2. **CI on every push** (GitHub Actions, no secrets needed): build, then tests, then scorecard. The run fails if a correctness KPI (section B) regresses, and the scorecard is uploaded as an artifact.
3. **README headline:** a 4-row table at the top (reuse ratio, inherited coverage, hybrid P@5 versus baselines, and cold start time), linking to the full scorecard.
4. **Browser Scorecard tab:** it reads `scorecard.json`, so judges see the numbers in the product.
5. **Video:** one 15-second beat shows the scorecard and the ablation chart.
6. **Tests:** pytest asserts every planted scenario. Each planted fact is one test, so "catch rate 100%" is literally the test suite passing.

## Honesty rules

- Estimated baselines are labelled as estimates.
- Results come from public frameworks and fictional company data. Say so wherever numbers appear.
- If a target is missed, publish the real number and a short note on why.
