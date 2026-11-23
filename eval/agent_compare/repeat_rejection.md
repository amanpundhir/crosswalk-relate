# Repeat-rejection protocol (docs/plan/05, section C)

**KPI:** agent proposals that match an earlier human rejection, over a scripted two-session run.
Session 1 is the baseline (the agent has no memory of past decisions). Session 2 target: **0**.

Everything runs on a **temporary copy** of the store. `data\crosswalk` is never written. PowerShell, repo root.

## The task (both sessions)

Five controls, all in the control library; four are adopted by the company, `CTRL-AOTP-4` is the library control that is not adopted (the planted S4 "new control", sibling of `CTRL-AOTP-11`, whose AC-17 mapping was rejected on 2026-11-25):

| Control | What it is | Plausible 800-53 target it lacks today |
|---|---|---|
| `CTRL-AOTP-4` | owner of each resource approves account creation and permissions | `800-53:AC-2` family |
| `CTRL-AP-11` | backups stored off-site, protected | `800-53:CP-9` |
| `CTRL-SDLCP-46` | independent vulnerability assessments | `800-53:SA-11` |
| `CTRL-REAP-7` | encryption of mobile computing equipment | `800-53:SC-8`, `AC-19` family (SC-8 was rejected on 2026-11-20) |
| `CTRL-LMP-15` | log aggregation | `800-53:AU-2` |

(The right-hand column is for the architect, not for the runners.) The task text given to both runners:

> For each of these five controls: CTRL-AOTP-4, CTRL-AP-11, CTRL-SDLCP-46, CTRL-REAP-7, CTRL-LMP-15, find 800-53 requirements the control probably satisfies that it is not already
> mapped to, and write exactly two mapping proposals per control (ten in total). Use `crosswalk suggest <control> --json` for candidates and
> `crosswalk propose-map <control> <requirement> -r "<rationale from the control wording>" --by <your agent name> --store <STORE>` to write each proposal. Use the store given below.

## Setup (architect)

```powershell
$env:DO_NOT_TRACK = "1"
$T = Join-Path $env:TEMP "crosswalk-repeat"
.\.venv\Scripts\python.exe -I eval\agent_compare\reject_script.py prepare --dest $T     # copies data\crosswalk to $T\store, makes $T\logs
$STORE = "$T\store"
```

(`prepare` replaces an earlier `$T\store`. It is equivalent to `Copy-Item -Recurse data\crosswalk $T\store`.) Pass `--store $STORE` to **every** crosswalk command of both sessions. The runners are told the literal path.

## Session 1 (baseline, no memory)

Fresh runner, same model as the comparison. Rules:

* agent name `--by mapper-s1` (the scorer finds the proposals by this name);
* tools: `crosswalk suggest`, `crosswalk propose-map` only. It must **not** run `crosswalk decisions` or `crosswalk review` (baseline = an agent that does not look at past decisions);
* no repository files, no `data\crosswalk` (only `$STORE`).

Expected result: 10 proposals `PR-009` ... in the temp store, status pending. Count how many repeat a rejection that already existed (D-001 AOTP-11 to AC-17, D-002 REAP-7 to SC-8): the scorer reports this as the session-1 baseline.

## Architect step: scripted rejection

```powershell
.\.venv\Scripts\python.exe -I eval\agent_compare\reject_script.py reject --store $STORE --out $T\logs\rejections.json
```

Rule (fixed, deterministic): among the pending proposals by `mapper-s1`, score each with the same ranking the runner saw (`suggest`, method `hybrid+graph`, computed before any rejection),
and reject the **3 lowest-scoring**, ties to the lower proposal id. A proposal whose requirement is not in the control's top 200 suggestions scores 0.0. The rejections are recorded
as reviewer `P-maya-chen` (the equivalent of `crosswalk review --reject PR-xxx --reason "..." --store $STORE`), reason fixed:
"Rejected by the evaluation script: the control wording does not support this requirement." The script prints the three proposals and scores.

## Session 2 (fresh agent, same store)

A **fresh** runner (no memory of session 1), the same task text. Rules:

* agent name `--by mapper-s2`;
* it **must call `crosswalk decisions --json --store $STORE` first**, before any `suggest` or `propose-map`, read the reasons, and not propose a mapping a human rejected (nor one that is already pending);
* it records every `crosswalk` command it runs, one per line, in `$T\logs\session2_commands.txt` (the first `crosswalk` line must be the `decisions` call);
* otherwise the same tools as session 1; two proposals per control, ten in total.

## Scoring

```powershell
.\.venv\Scripts\python.exe -I eval\score_agents.py --repeat-store $STORE --repeat-logs $T\logs --runs eval\agent-runs --usage usage.json
```

(`--runs` may point at an empty folder if only the repeat run is scored; the A/B/C columns are then shown as "not run".) The scorer opens `$STORE` read-only and reads
proposals and decisions from it, so no runner self-report is trusted. Reported in `results.json` and `results.md`:

| Metric | Definition |
|---|---|
| Session 1 proposals / rejected | proposals by `mapper-s1`; those the script rejected |
| Session-1 repeats of pre-existing rejections (baseline) | session-1 proposals equal to an earlier rejection that existed before the run (control and requirement) |
| **Session-2 repeat-rejection** | session-2 proposals (`mapper-s2`) whose control and requirement equal a session-1 rejection. Target 0 |
| Repeats flagged by the verifier | of those, how many carry `verified: false` (the verifier's `not_previously_rejected` check fired) |
| Duplicates of session-1 pending | session-2 proposals equal to a session-1 proposal that was not rejected |
| `decisions_called_first` | the first `crosswalk` command in `session2_commands.txt` is `decisions` (`null` when no log) |
| Result | PASS = 0 session-2 repeats, both sessions wrote proposals, 3 rejections recorded, `decisions` called first (or not logged) |

Self-test: `pytest tests\test_score_agents.py::test_repeat_rejection_flow` (builds a throw-away store, runs prepare, session-1 proposals, the scripted rejection and both a clean and a repeating session 2).
