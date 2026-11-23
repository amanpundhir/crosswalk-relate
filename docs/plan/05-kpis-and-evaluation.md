# 05 · KPIs and evaluation

**Core claim:** *An agent that works through the Crosswalk graph gives correct, checkable compliance answers and proposals. The same agent working from spreadsheets does not. The graph also reduces duplicated audit work and flags risk early.*

## Where the correct answers come from

| Source | What it gives us | How we use it |
|---|---|---|
| **NIST official crosswalk** | The correct mappings between real requirements | Held out. Hybrid search and the mapper agent are scored against it. |
| **Planted scenarios** in the company pack | Known answers to the six core questions, plus planted traps: a mapping that is only proposed, an expired evidence item, an earlier rejection, a single-owner control | `eval/ground_truth.yaml`, written **before** the queries and prompts |
| **Golden questions** | 20 natural-language questions with exact expected answers | The expected answers come from our own Cypher, so they are deterministic |
| **Planted bad proposals** | Proposals that must fail verification: duplicates, previously rejected, non-existent targets | `eval/bad_proposals.yaml` |
| **Manual baseline** | Time to answer 5 questions from a spreadsheet export | We time ourselves and label the result as an estimate |

## KPI table

### A. Agent reliability (the headline: "connected context makes the agent reliable")

We use the same model, the same 20 golden questions and the same prompts in three setups:

| KPI | Agent with spreadsheets (CSV export) | Agent with the graph, no claim check | **Agent with the graph and the claim checker** |
|---|---|---|---|
| Answer accuracy (exact match) | measured | measured | target ≥ 90% |
| Claims with a valid citation | n/a | measured | target 100% of shown claims |
| **Wrong claims shown to the user** | measured | measured | target **0** (they are caught and flagged) |
| Trap hits (e.g. counts a proposed mapping as covered) | measured | measured | target 0 |
| Tokens per question | measured | measured | measured |
| Tool calls per question | measured | measured | measured |

Running this needs a model API key, so judges can't re-run it for free. We publish **all transcripts** in `eval/agent-runs/`, the exact prompts and a re-run script. The README says this plainly.

### B. Mapping quality (backs "the suggestions can be trusted with review")

Each method is scored against the NIST crosswalk:

| Method | Precision@5 | Recall@10 | MRR |
|---|---|---|---|
| Full-text only | measured | measured | measured |
| Vector only | measured | measured | measured |
| Hybrid (WRRF) | measured | measured | measured |
| Hybrid plus graph re-rank | measured | measured | measured |
| **Mapper agent** (reads the candidates with graph context and decisions) | measured | measured | measured |

Targets: hybrid beats each single method, and graph re-rank and the agent improve on hybrid. We publish whatever the real numbers are.

**Realism check:** control text comes from real open-source policy templates written by other people, not text we wrote to match NIST. So the mapping scores reflect wording a real company would have. Ground-truth mappings for template controls are labelled by hand for a sample of about 40 controls. NIST's crosswalk covers requirement-to-requirement links, not company controls.

### C. Guardrails (backs "the graph keeps the agent honest")

| KPI | Definition | Target |
|---|---|---|
| Claim-checker catch rate | Planted false claims (e.g. citing an expired path) that get flagged | 100% |
| Bad-proposal catch rate | Planted bad proposals that fail verification | 100% |
| **Repeat-rejection rate** | Agent proposals matching an earlier human rejection, measured over a scripted 2-session run | Session 1: baseline. Session 2: 0. |
| Unauthorised writes | Agent writes outside the `propose_*` tools | 0. Enforced by design and tested. |
| Concurrent-write integrity | In the two-agent run, lost updates divided by total writes | 0 |
| **Live-catch reproducibility** | The live-catch scenario (expired evidence plus a mapping that is only proposed) is caught with the right reasons | 10 / 10 replays. 10 / 10 fresh agent runs, or report the real count. |
| Auditor-packet integrity | Packet lines that cite a path failing the claim check but are not marked ⚠ | 0 |

### D. Core correctness (backs "it works", and runs without AI)

| KPI | Definition | Target |
|---|---|---|
| Planted-gap catch rate | Planted gaps found by Q1 | 100% |
| Blast-radius accuracy | Q3 output compared with the expected set | Exact match |
| Adopt accuracy | Q2 output compared with the expected set | Exact match |
| False alarms | Items flagged that are not planted | 0 |

### E. User impact (backs "useful")

| KPI | Definition | How it is shown |
|---|---|---|
| Evidence reuse ratio | Distinct requirements satisfied per evidence item, across frameworks | README headline |
| Duplicate collections avoided | Evidence requests across audits already covered by the same item | Scorecard |
| Inherited coverage | Share of a new framework already met through the crosswalk | `adopt` output |
| Early warning lead time | Days from the blast alert to the first affected audit | Scorecard |
| Time to answer | Seconds for the agent or CLI, compared with the manual estimate | Scorecard and video |
| Evidence requests drafted | Requests the evidence agent drafts for expiring items, per run | Scorecard |

### F. System and reproducibility

| KPI | Target |
|---|---|
| Cold start to first result (no AI), Windows and Linux | ≤ 5 min |
| **Agent setup**: `crosswalk agent setup` to a passing self-test | 1 command, ≤ 2 min, no manual config edits |
| `crosswalk build` time (embeddings cached) | ≤ 60 s |
| Query and tool latency, p95 | < 200 ms |
| Claim-check time per answer | < 500 ms |
| Browser explorer interactive | < 3 s |
| Store size | < 25 MB |
| Deterministic build | identical content across two runs |

## How the KPIs fit into the project

1. **One command:** `crosswalk scorecard` runs sections B to F against the committed store and the ground truth, with no AI. Section A and the agent parts of B and C are read from the latest published `eval/agent-runs/`. Output goes to `eval/scorecard.json` and `eval/scorecard.md`.
2. **Tests encode the truth.** Every planted gap, trap and bad proposal has its own pytest. Catch rates are literally the test suite passing.
3. **CI on every push**, with no secrets: build, tests, scorecard, the JSON export check and the Pages deploy. The run fails if any D or C guardrail KPI goes down.
4. **README headline table** (4 rows):
   - agent accuracy with spreadsheets vs. with the graph and claim checker
   - wrong claims shown (n vs. 0)
   - reuse ratio
   - cold start time
5. **Browser:** a Scorecard tab and an Agent log tab, both reading from the graph and `scorecard.json`.
6. **Video:** a 15-second beat on the three-column agent comparison.

## Honesty rules

- Company data is fictional, and baselines are estimates. Both are labelled wherever they appear.
- The agent comparison covers one model, one question set and published transcripts. We make no broad claims beyond that.
- If a target is missed, we publish the real number with a short note.
