# 06 · Build plan, risks, video and submission

Today is **Sun Nov 22, 2026**. The deadline is **Fri Dec 11, 6:00 PM PST**. We aim to submit by **Thu Dec 10**, which leaves one day of buffer.

The plan follows three playbook rules: build a **thin version that works end to end first**, build the evaluation alongside the features, and keep **at least 20% of the time for presentation** (Dec 7 to 10).

## Milestones

| Dates | Milestone | Done when |
|---|---|---|
| **Nov 22 to 23** | Setup and data check | Public repo with the topics `relate` and `relate-neo4j-hackathon`, an Apache-2.0 licence, and these plan docs committed. NIST files downloaded and licences recorded in `inputs/nist/SOURCES.md`. Relate CLI and `relate-db` installed. `RETURN 1` works. Confirmed that `--read-only=live` works next to a writer on Windows. |
| **Nov 24 to 25** | Templates, company pack and ground truth | One open-source policy template set is chosen (licence confirmed) and copied to `inputs/templates/` with attribution. `inputs/company/` is built on top of it. `eval/ground_truth.yaml`, the golden questions, the bad proposals, the hand-labelled control mappings (~40) and the **live-catch scenario** are written **before** any query or prompt. |
| **Nov 26 to 27** | **Thin end-to-end version** | Ingesting 800-53, 800-171, the crosswalk and the company pack produces `data/crosswalk/`. `crosswalk coverage` prints a real result. The store is committed. |
| **Nov 28 to 29** | Core questions | Q1 to Q4, Q6 and Explain are done as `.cypher` files plus CLI commands. Results include path ids. There is one pytest per planted fact. Scorecard v1 exists and CI runs. |
| **Nov 30 to Dec 1** | Hybrid suggest plus mapping evaluation | Embeddings, vector and full-text indexes, WRRF fusion and the graph re-rank are built. The section B ablation runs. |
| **Dec 2** | Proposals, verifier, review | `:Proposal`, the proposal verifier, `crosswalk review` (one transaction per decision), and `:Decision` and `:Change` nodes all work. |
| **Dec 3 to 4** | **Agent core** | Built: `crosswalk-mcp` (read tools with path ids, `propose_*`, `decisions`, `check_claims`), the claim checker, the audit-prep and mapper prompts, and **`crosswalk agent setup`** (skill install, both MCP servers registered, self-test, `--dry-run` and `--undo`). Flows A, **A2 (the live catch, plus `crosswalk demo live-catch`)** and B work in Claude Code. |
| **Dec 5** | Remaining agents and agent evaluation | Evidence agent and **auditor-packet agent** done. The **two-agent concurrent run** shows a conflict and a retry. The three-column agent comparison, the two-session repeat-rejection run and 10 live-catch replays are complete, with transcripts saved. |
| **Dec 6** | Browser explorer | `graph.cypher` export, WASM Coverage, Blast, Agent log, What-if and Scorecard tabs, and a GitHub Pages deploy. |
| **Dec 7 to 8** | Docs | README in the official template order. Also: schema diagram, query cookbook, agent setup guide, responsible AI and limits, "Built with" list, AI disclosure and screenshots. |
| **Dec 9** | Video | Recorded and edited to 1:50, uploaded unlisted, and checked to play when logged out. |
| **Dec 10** | Freeze and submit | Cold-start test on a clean Windows machine and on Linux. Checklist below done. Submitted on Devpost. |
| **Dec 11** | Buffer | Fixes only. |

**In scope by decision:** the auditor-packet agent, CSF 2.0 and the two-agent demo stay in the plan. They are **not** stretch goals.

**Scope cuts if we fall behind, in this order** (only polish, never features we've committed to):

1. Graph re-rank (keep plain hybrid search)
2. Browser What-if buttons (keep the read-only tabs)
3. Cursor support in `agent setup` (keep Claude Code)
4. Extra golden questions beyond 20

**Never cut:** the committed store, the claim checker, **the live catch**, the proposal verifier, all four agents, CSF 2.0, the two-agent demo, `crosswalk agent setup`, the agent comparison, the scorecard, the README template and the cold-start test.

**Timeline warning:** keeping everything in scope makes Dec 3 to 6 very tight. If the agent core isn't working by **Dec 4 evening**, that is the signal to move to the cut list above and possibly take a day from the video (Dec 9).

## Commit habit

Make small commits every day from Nov 22. A steady history shows sustained effort, and it proves the work started inside the contest period (rule 3).

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| NIST file formats or licences differ from what we expect | Medium | Check on day 1. If needed, fall back to the 800-53 ↔ 800-171 mapping only. |
| The agent ignores the "cite path ids" rule | **High** | The tools return path ids, so citing is the easy path. The claim checker drops uncited claims. Prompts include worked examples. Measure it, don't assume it. |
| Agent runs are slow or costly | Medium | 20 questions × 3 setups is small. Cache the transcripts. Judges read them rather than re-running. |
| `--read-only=live` beside a writer behaves differently on Windows | Medium | Check on day 1. Fallback: one MCP server (ours) owns the connection and exposes a read-only Cypher tool. |
| Relate preview features change | Low | Use stable features only. `COMBINE` is optional. |
| WASM can't open the directory store | Known | Export a Cypher script. The browser copy lives in memory. |
| Embedding model is too big for judges | Medium | Ship precomputed embeddings. Fall back to full text at query time. |
| A judge reads it as claiming to certify compliance | Low | Clear "not audit advice" note. Suggestions stay as proposals. |
| The policy template licence is share-alike (CC BY-SA) or unclear | Medium | Keep the templates in `inputs/templates/` under their own licence, apart from our code. If unclear, switch to the other candidate set. |
| `agent setup` edits the user's agent config wrongly | Medium | `--dry-run` first, show the changes, ask before writing, back up the config, provide `--undo`. |
| The live catch depends on the agent making the wrong claim | Medium | It is a planted scenario based on the spreadsheet's "✔". The replay mode always shows it, and fresh-run success is reported honestly. |
| Overlap with "decision memory" entries (precedent, hive4j, whygraph) | Medium | Our memory is tied to compliance facts and is measured (repeat-rejection rate). Say that clearly in the README. |
| Time | Medium | Thin version by Nov 27. Scope cuts listed above. |

## Demo video outline (1:50; the limit is 2:00)

| Time | Beat | On screen |
|---|---|---|
| 0:00 to 0:12 | Problem | "Three frameworks, hundreds of rules, the same screenshot collected three times, and an AI that guesses." |
| 0:12 to 0:20 | Theme | "An audit-prep agent that answers with receipts." Schema animates in. |
| 0:20 to 0:55 | **The live catch (wow moment)** | Maya: "Is MFA covered for 800-171?" The agent says confidently: "Yes, fully covered." **Pause. Then the claim check runs on screen:** ✖ "EV-044 expired Dec 1", ⚠ "CTRL-012 mapping only proposed". The corrected answer appears. Cut to the browser, where the broken path glows red. Caption: *"The spreadsheet said ✔. The graph knew better."* |
| 0:55 to 1:15 | Flow B | New control. The mapper proposes 3 and **skips one Maya rejected last week**. The verifier marks them. Maya approves 2 in `review`. Coverage moves. |
| 1:15 to 1:25 | Two agents plus the packet | Conflict, retry, both land (log). Then the auditor-packet agent generates the Jan 15 packet with ⚠ items marked. |
| 1:25 to 1:40 | Evidence | Three-column table: spreadsheet agent vs. graph agent vs. graph agent with the checker (accuracy, **wrong claims shown: n → 0**, tokens). Reuse ratio. |
| 1:40 to 1:50 | Close | `crosswalk agent setup` (one command), `data/crosswalk/` on GitHub, "runs without AI too". Repeat the theme. |

## Final README order

1. Title with keywords (Relate, compliance, NIST, AI agent, MCP) and the one-line theme
2. Video link, explorer link, headline scorecard, and the **"Why not Vanta?" line**: *"Crosswalk is free, runs locally, and lets you inspect every link in the graph. It works with any MCP agent, it is built on NIST's official crosswalk, and its accuracy is measured and published."*
3. A GIF or screenshot of the **live catch**
4. **Use case:** Maya's scenario and who benefits
5. **How it uses Relate:** directory mode, why this mode (readers next to writers for several agents), and what the graph models (facts plus agent memory diagram)
6. Requirements and criteria map (from 03)
7. **Setup and run:**
   - (a) core, no AI: Windows and macOS/Linux, three commands
   - (b) agents: **one command, `crosswalk agent setup`**, then example prompts
   - (c) `crosswalk demo live-catch` (no AI key needed)
8. **Where the data lives:** `data/crosswalk/` and how to inspect it
9. Evaluation: the agent comparison, mapping quality, guardrails and the scorecard
10. Responsible AI and limits, data sources and licences (**including the policy template set's licence and attribution**)
11. Built with (Relate features, third-party tools, AI tools), AI disclosure and reused code

## Pre-submission checklist

- [ ] The theme line appears on the explorer landing view, at the top of the README and in the video.
- [ ] Every criterion maps to a feature a judge can find in under a minute (03).
- [ ] The agent comparison and scorecard numbers are published, with transcripts.
- [ ] The claim checker, proposal verifier, human approval and audit trail all work and are visible.
- [ ] Every Relate feature we claim is wired in: directory store, Cypher paths, hybrid search, transactions, MCP, skill, WASM.
- [ ] The core runs on a cold clone with **no API key**, on Windows and Linux.
- [ ] `crosswalk agent setup` works on a clean machine and its self-test passes. `--undo` removes everything it added.
- [ ] `crosswalk demo live-catch` works with no AI key, and the live catch is in the video and the README GIF.
- [ ] The "Why not Vanta?" line is near the top of the README.
- [ ] The policy templates are credited, and their licence file sits next to them.
- [ ] The explorer loads on GitHub Pages from a cold browser.
- [ ] Commit history is steady from Nov 22 to Dec 10.
- [ ] Every claim in the README is true, and the fictional data is labelled as fictional.
- [ ] The repo is public, tagged `relate` and `relate-neo4j-hackathon`, and visible at github.com/topics/relate.
- [ ] An Apache-2.0 LICENSE and `.env.example` are present, with no secrets in the history.
- [ ] All Devpost fields are filled: title, "what connects to what", repo, video (plays logged out), screenshots, Relate features used, third-party tools, AI disclosure and reused-code disclosure.

## After the event

Keep the repo public and tagged through Dec 17. After the winners are announced, compare our entry with theirs on theme, evidence, criteria coverage, presentation and effort, and write down the lessons. The only hosting is GitHub Pages, so there is nothing to tear down.
