# Agent comparison protocol (docs/plan/05, section A)

Same model, same 20 golden questions, same preamble, three tool setups. The architect launches the runners;
this file is the exact instruction set. Scoring is mechanical: `python -I eval\score_agents.py`.
Windows, PowerShell. The store date (`as_of`) is **2026-12-02**; every runner is told that date and nothing else about the company.

| Setup | Folder for answers | Runner may use | Runner may not use |
|---|---|---|---|
| **A. spreadsheet** | `eval\agent-runs\A-spreadsheet\` | read `eval\agent_compare\spreadsheet\*.csv`; Python or PowerShell on those files | any `crosswalk` command, any other repo file |
| **B. graph, no checker** | `eval\agent-runs\B-graph\` | read-only `crosswalk` commands with `--json`; Python or PowerShell on their output | `crosswalk check`, any write command, any repo file |
| **C. graph + checker** | `eval\agent-runs\C-graph-checker\` | as B, plus `crosswalk check <answer.json> --json` | any write command, any repo file |

All three runners may also read `eval\agent_compare\questions.jsonl` (the 20 questions and the keys of `structured`)
and `eval\agent_compare\answer_template.jsonl`. They contain no expected values.

**Never readable by any runner:** `eval\golden_questions.yaml`, `eval\ground_truth.json`, `eval\oracle.py`, `eval\planted.yaml`,
`inputs\`, `src\`, `tests\`, `docs\`, `data\`, `exports\`, `out\`, other runs' folders. The architect should say so in the prompt and
check the transcript of each run for violations (a violating run is discarded and redone).

## Before the run (architect)

1. `python -I eval\score_agents.py --write-protocol-files` (only if `golden_questions.yaml` changed) and `python -I eval\agent_compare\make_spreadsheet.py` (only if the pack changed).
2. The store must be built: `.\.venv\Scripts\crosswalk.exe build` (A does not need it, B and C do).
3. Remove old answers: `eval\agent-runs\A-spreadsheet\`, `B-graph\`, `C-graph-checker\`.
4. Use the same model for every runner. Preferred: one fresh subagent per (setup, question), 60 runs. Acceptable: one fresh subagent per setup that answers the 20 questions one by one, treating each as independent. Record each subagent's token count and wall time.
5. After the runs write `usage.json` (see "Scoring"), then run the scorer.

## Shared preamble (paste first into every runner prompt)

> You are a compliance analyst for Harbor & Pine (fictional, 85 staff). Today is 2026-12-02. Maya Chen, the security lead, will read your answer.
> Answer the question below using ONLY the tools and files your setup allows. Be exact: counts, ids and dates must be right. If your data cannot
> answer a part, put `null` (or `[]` for an empty list when you are sure it is empty) in `structured`; do not guess.
> Output one JSON object (one line) appended to `<your answers.jsonl>` with exactly these fields:
> `id`, `answer_text` (2 to 5 plain sentences to Maya), `structured` (the keys listed for this question in `questions.jsonl`, values typed as
> described there), `claims`, `tool_calls`.
> Claim rules and formats are in the "Answer line" section of this README, which the architect pastes after this preamble.

## Answer line (identical for all setups)

One JSON object per question, one line per object, appended to `eval\agent-runs\<setup>\answers.jsonl` (UTF-8):

```json
{"id": "GQ-05", "answer_text": "...",
 "structured": {"covered_direct": false, "inherited": false, "evidence": "EV-044", "evidence_expired_at": "2026-12-01",
                "approved_control_with_valid_evidence": [], "proposed_only_controls": ["CTRL-PWP-4"]},
 "claims": [{"text": "03.05.03 is not covered: EV-044 expired on 2026-12-01", "path_ids": ["P-..."], "kind": "coverage", "asserts": "invalid"}],
 "tool_calls": 4}
```

* `structured`: keys exactly as in the table below. Ids verbatim (`800-171:03.05.03`, `CTRL-REAP-6`, `EV-044`, `AUD-171`, `P-dana-okafor`, `SYS-idp`),
  dates `YYYY-MM-DD`, percentages with two decimals, id lists without duplicates (order does not matter).
* `tool_calls`: number of tool calls you made to find the answer (every shell, read, search call), not counting the write of the answer. Setup C also adds `"check_calls": <number of crosswalk check runs>`.
* `claims` (setups B and C; setup A writes `[]`): every factual sentence you rely on, one object each:
  * `text`: the sentence.
  * `path_ids`: path ids copied **verbatim** from the tool JSON (`path_id`, `paths[].id`, `proposed_paths[].id`, `inherited_paths[].id`, `paths_one_hop[].id`, `dependency_paths[].id` ...). Never write or edit a path id by hand; a made-up id counts as a wrong claim.
  * `kind`: `"coverage"` when the claim says a requirement is covered (then the cited path must reach evidence), otherwise omit.
  * `asserts`: `"valid"` (default) when the claim says the cited path holds today; `"invalid"` when you cite a failing path to show something is NOT covered, expired, only proposed or rejected.
  * `aggregate: true` for a pure total taken from a tool summary that has no path (for example "15 of 97 covered"). Use it sparingly; everything about a specific requirement, control, evidence item, person or audit needs a path.
* A claim with no path id is "uncited". A `valid` claim whose path is expired, only proposed, rejected, not adopted or unknown is a **wrong claim shown**.

### `structured` keys per question

| Id | `structured` keys (type) |
|---|---|
| GQ-01 | `active_requirements` int, `direct` int, `inherited` int, `gap` int, `percent_direct` number, `percent_direct_plus_inherited` number |
| GQ-02 | `active_requirements` int, `direct` int, `inherited` int, `gap` int, `percent_direct` number |
| GQ-03 | `active_requirements` int, `direct` int, `inherited` int, `gap` int, `percent_direct_plus_inherited` number |
| GQ-04 | `count` int, `requirements` [string] |
| GQ-05 | `covered_direct` bool, `inherited` bool, `evidence` string, `evidence_expired_at` date, `approved_control_with_valid_evidence` [string], `proposed_only_controls` [string] |
| GQ-06 | `controls` [string] |
| GQ-07 | `evidence` [string], `broken_800_171_count` int, `broken_800_171` [string] |
| GQ-08 | `cutoff` date, `expiring_evidence` [string], `affected_audits` [string], `broken_counts` {800-53: int, 800-171: int, CSF: int} |
| GQ-09 | `still_inherited` [string], `broken_and_not_inherited` [string] |
| GQ-10 | `controls` [string] |
| GQ-11 | `at_risk` bool, `control` string, `requirement_still_covered` string, `valid_replacements` [string], `in_blast_30d` bool, `in_blast_until_audit_171` bool |
| GQ-12 | `allowed` bool, `previously_rejected` bool, `decided_by` string, `decided_at` date, `reason` string |
| GQ-13 | `rejections` [{control, requirement, decided_at}] |
| GQ-14 | `controls` [string] |
| GQ-15 | `person` string, `sole_owned_count` int, `controls` [string], `high_criticality_systems` [string] |
| GQ-16 | `requirements` [string] |
| GQ-17 | `evidence` string, `direct_requirements` int, `frameworks_direct` [string], `frameworks_reached` [string], `reach_count_1_hop` int, `requested_by` [string] |
| GQ-18 | `evidence` [string] |
| GQ-19 | `evidence` [string] |
| GQ-20 | `covered_direct` bool, `paths` [{control, evidence, expires_at, valid}] |

`questions.jsonl` carries the question text and a short hint per key (for example "percent, 2 decimals"). `answer_template.jsonl` has one empty line per question.
Extra keys are ignored by the scorer; a missing key or `null` is wrong.

---

## A. Spreadsheet agent

**Runner may read only** `eval\agent_compare\spreadsheet\` (plus `questions.jsonl`, `answer_template.jsonl`):

| File | Content |
|---|---|
| `legacy_tracker.csv` | the team's old tracker: control, requirement ids, owner (as last typed), status text, last reviewed |
| `controls_list.csv` | control id, policy, statement, current owner(s), systems, implementation status, requirement ids from approved mappings |
| `evidence_list.csv` | evidence id, title, type, owner, controls supported, collected, expires, status as of 2026-12-02, audits that request it |
| `audits_list.csv`, `systems_list.csv` | audit dates and scope; system criticality |
| `requirements_catalog.csv` | the active requirement ids and titles of 800-53, 800-171 and CSF (a catalogue, no links between them) |

What a spreadsheet team would not have and the files therefore do not contain: the NIST crosswalk (800-53 to 800-171 to CSF links), earlier
approval or rejection decisions with reasons, pending mapping proposals, path ids. Questions that need them cannot be answered exactly from these files;
the runner answers as well as it can and leaves what it cannot know as `null`.

**Rules.** No `crosswalk` command. No file outside the folder above. Python or PowerShell may read these CSVs (scripts go in a temp folder, not in the repo).
`claims` is `[]`. `tool_calls` counts every read or script run.

**Prompt.** Shared preamble, then: "Setup A. Your only data is the CSV files in `eval\agent_compare\spreadsheet\`. Do not run any `crosswalk` command and do not read any other file
in the repository. Append your answer line to `eval\agent-runs\A-spreadsheet\answers.jsonl`. Question GQ-xx: <question text>. Keys of `structured`: <row from the table>."

## B. Graph agent, no claim checker

**Runner may run only read-only Crosswalk CLI commands, always with `--json`**, from the repo root, in PowerShell:

```powershell
$env:DO_NOT_TRACK = "1"
.\.venv\Scripts\crosswalk.exe coverage -f 800-171 --json            # also -f 800-53 / CSF, --detail, --status gap|covered|inherited, --audit AUD-53
.\.venv\Scripts\crosswalk.exe adopt CSF --json                       # or 800-171
.\.venv\Scripts\crosswalk.exe blast --days 30 --json                 # or --until 2027-01-15, or --audit AUD-171
.\.venv\Scripts\crosswalk.exe reuse --top 10 --json
.\.venv\Scripts\crosswalk.exe owners --json
.\.venv\Scripts\crosswalk.exe explain 800-171:03.05.03 --json
.\.venv\Scripts\crosswalk.exe decisions --json                       # or --about CTRL-AOTP-11
.\.venv\Scripts\crosswalk.exe suggest CTRL-AOTP-4 --json
.\.venv\Scripts\crosswalk.exe stale --json                          # legacy tracker says Compliant, the graph disagrees
.\.venv\Scripts\crosswalk.exe evidence --audit AUD-171 --status expired --json   # or --status lapsed|expiring|valid, --until 2027-01-15
```

Allowed commands: `coverage`, `adopt`, `blast`, `reuse`, `owners`, `explain`, `decisions`, `suggest`, `stale`, `evidence`. The runner may post-process the JSON with Python or PowerShell (filter, count, sort) but may not import `crosswalk`,
open `data\` or any repo file, pass `--store` or `--as-of`, or run `check`, `propose-map`, `review`, `build`, `packet`, `agent`, `demo`.
It **must not run `crosswalk check`**; it writes its answer once and is done.

**Prompt.** Shared preamble, then: "Setup B. Use the read-only `crosswalk` commands above (always `--json`) and cite path ids from their output in `claims`. Do not run `crosswalk check` or any
command that writes. Do not read repository files. Append your answer line to `eval\agent-runs\B-graph\answers.jsonl`. Question GQ-xx: <question text>. Keys of `structured`: <row from the table>."

## C. Graph agent + claim checker

Same tools as B plus the checker. Procedure for every question:

1. Gather data with the commands above; write the first answer (draft) as a checker input file in a temp folder, for example `$env:TEMP\crosswalk-draft\GQ-05.json`:
   `{"question": "<text>", "agent": "setup-c", "claims": [{"text": "...", "path_ids": ["P-..."], "kind": "coverage"}]}` (same `claims` objects as in the answer line, `asserts` may be left out).
2. Run `.\.venv\Scripts\crosswalk.exe check $env:TEMP\crosswalk-draft\GQ-05.json --json` (never `--persist`). Each claim gets a verdict: `verified`, `partial` (for example only a proposal) or `failed` (expired evidence, rejected, not adopted, unknown path, no receipt) with a reason.
3. **Correct the answer per the check before finalising**:
   * a claim that the checker marks `partial` or `failed` and that you assert as true must be removed or rewritten so it says what is actually true (for example "03.05.03 is NOT covered: EV-044 expired 2026-12-01"), and then
     it is kept with `"asserts": "invalid"` and the failing path as its path id (the checker's `failed` on such a claim is the expected evidence, not an error);
   * update `answer_text` and `structured` to match the corrected claims (a coverage count or a "covered" boolean that rested on a failed claim changes);
   * run the check again on the corrected claims; stop when every `valid` claim is `verified`. At most 3 check runs per question.
4. Append the final line to `eval\agent-runs\C-graph-checker\answers.jsonl` with: the final `claims`, `check_calls` (number of check runs), `tool_calls` (including check runs), and
   `draft_claims` (the claims of the first draft, unchanged, so the scorer can report how many wrong claims the checker caught).

**Prompt.** Shared preamble, then: "Setup C. Use the read-only `crosswalk` commands (always `--json`) to gather facts, cite path ids, then write your draft claims to a file and run
`crosswalk check <file> --json`. Correct your answer according to the check before you finalise it (rules: README setup C). Do not run any command that writes (never `--persist`).
Do not read repository files. Append your final line to `eval\agent-runs\C-graph-checker\answers.jsonl`. Question GQ-xx: <question text>. Keys of `structured`: <row from the table>."

---

## Scoring

```powershell
$env:DO_NOT_TRACK = "1"
.\.venv\Scripts\python.exe -I eval\score_agents.py --usage usage.json
```

`usage.json` (the architect fills it from subagent usage; fields may be omitted):

```json
{"A-spreadsheet":   {"tokens_total": 0, "seconds_total": 0},
 "B-graph":         {"tokens_total": 0, "seconds_total": 0},
 "C-graph-checker": {"tokens_total": 0, "seconds_total": 0}}
```

Outputs: `eval\agent_compare\results.json` and `results.md` (the three-column table from `docs\plan\05`, section A, plus a per-question grid).
Options: `--runs DIR` (default `eval\agent-runs`), `--store PATH` (default `data\crosswalk`, opened read-only to re-run the cited paths), `--out-dir DIR`.
A setup is "not run" when its `answers.jsonl` does not exist. Self-test: `pytest tests\test_score_agents.py`.

| Row of the table | Rule |
|---|---|
| Answer accuracy | question correct iff every key of `structured` matches `expected`: integers and strings exact, floats within 0.01, id lists as sets, lists of objects as sets of the expected keys, booleans exact. `reason` in GQ-12 is shown, not scored. |
| Claims with a valid citation | B, C: non-aggregate claims whose `valid` assertion is `verified` by `crosswalk.claims`, or whose `invalid` assertion cites a failing, known path. Share of all non-aggregate claims. |
| Wrong claims shown | B, C: `valid` claims with verdict `failed` or `partial`; `invalid` claims whose paths all re-run valid or include an unknown path. A has no paths: the table shows wrong answers instead. |
| Trap hits | question has a `trap` and the answer is wrong in the trap's direction (for example GQ-05 says "covered", GQ-11 says "at risk", GQ-14 misses the unowned control, GQ-17 names another evidence item). Rules: `TRAP_RULES` section in `eval\score_agents.py`; default is any wrong answer. |
| Tokens, time | from `usage.json`, divided by answered questions. |
| Tool calls | mean of `tool_calls` per answered question. |

Extra rows for setup C: wrong claims in the drafts (`draft_claims`) and how many the checker removed before the final answer.

## Honesty notes

One model, one question set, fictional company. The spreadsheet files are generated from the same pack (`eval\agent_compare\make_spreadsheet.py`) and
deliberately contain everything a normal tracker holds except the crosswalk, the decision log and path ids. All transcripts are published in `eval\agent-runs\`.
The repeat-rejection run (docs/plan/05, section C) has its own protocol: `repeat_rejection.md`.
