# 06 · Build plan, risks, video and submission

Today is **Sun Nov 22, 2026**. The deadline is **Fri Dec 11, 6:00 PM PST**. Our own target is to submit by **Thu Dec 10**, keeping one day of buffer.

The plan follows three playbook rules:

- Build a **thin end-to-end version first**.
- Build the evaluation alongside the features.
- Keep **at least 20% of the time for presentation** (Dec 7 to 10).

## Milestones

| Dates | Milestone | Done when |
|---|---|---|
| **Nov 22 to 23** | Setup and data check | All of these are true:<br>• A public repo exists with the topics `relate` and `relate-neo4j-hackathon` and an Apache-2.0 licence.<br>• The plan docs are committed.<br>• Licences for CISA CSAF, KEV and ATT&CK for ICS are confirmed in `inputs/public/SOURCES.md`.<br>• The Relate CLI and `relate-db` are installed, and `RETURN 1` works.<br>• Relate's `clone`, `.rl` read-only and MCP behaviour are confirmed on Windows. |
| **Nov 24 to 25** | Fictional plant v1 plus ground truth | `inputs/fernhollow/` has about 150 assets, about 90 rules, the networks, processes and required flows. `eval/ground_truth.yaml` lists every planted problem and decoy, **written before any query**. |
| **Nov 26 to 27** | **Thin end-to-end version** | `waterline build` produces `data/fernhollow.rl`. `waterline paths --to critical` prints the real planted paths. The file is committed. |
| **Nov 28 to 30** | Core questions | Q2 to Q5 and Q7 are done, with CSAF advisory ingest and version matching. There is one pytest per planted fact. `waterline scorecard` v1 exists. CI runs, including the offline job. |
| **Dec 1 to 2** | What-if and human in the loop | Clone-to-verify (Q6), required-flow checks, `propose`, `review` with transactions, `:Change` records and `report --md`. |
| **Dec 3 to 4** | Agent | Skill install, MCP read-only server, triage agent flow, the 20 golden questions, and the graph-vs-CSV comparison run with transcripts saved. The two-agent transaction demo works. |
| **Dec 5 to 6** | Browser viewer | `graph.cypher` export, WASM loads it **from local files**, and the Map, Paths, What-if and Scorecard tabs work. It is also deployed to GitHub Pages. |
| **Dec 7 to 8** | Docs | The README is in the official template order. There are a schema diagram and a query cookbook, sources and licences, a responsible-use section, a "Built with" list, an AI disclosure and screenshots. |
| **Dec 9** | Video | Recorded and edited to 1:50, uploaded as unlisted, and checked to play when logged out. |
| **Dec 10** | Freeze and submit | Cold-start test on a clean Windows machine and on Linux, plus an offline test. The checklist below is run and the entry is submitted on Devpost. |
| **Dec 11** | Buffer | Fixes only. |

**Scope cuts if behind (in this order):**

1. ATT&CK technique labels
2. The two-agent demo
3. Browser What-if (keep a read-only view)
4. The GitHub Pages copy (keep the local HTML)

**Never cut:** the committed `.rl` file, the planted-problem tests, the scorecard, the offline CI job, the README template and the cold-start test.

## Commit habit

Commit small changes every day from Nov 22. Rule 3 requires the work to start inside the contest period, and a steady history shows that.

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| CSAF product and version data is messy, so matching is hard | **High** | Pick ~30 advisories for 4 to 5 vendors and normalise their product names by hand in a mapping table. Labelled ground truth catches mistakes. |
| The fictional plant looks unrealistic to OT-savvy judges | Medium | Base the zones on the standard Purdue model and the CISA/EPA asset-inventory guidance. Use real PLC models, real ports (502, 44818, 102, 20000) and realistic mistakes taken from the 2026 alerts (cell modems, vendor VPNs). |
| The WASM viewer won't load from `file://` (browsers block wasm fetch from local files) | **High** | Option 1: inline the wasm and data into one HTML file (base64). Option 2: `waterline view` starts Python's built-in local web server. Test both on day 1 of the viewer. |
| `.rl` lock confuses users (read-only refused while a writer is open) | Medium | Writes are short and only `review` and `build` write. Errors say what to do. |
| Relate preview features change | Low | Use only stable features. No preview flags are needed. |
| The agent comparison needs an API key | Known | Publish transcripts and prompts. The core product needs no key. |
| Someone reads it as an attack tool (contest rule 10) | Low | Defensive framing everywhere. No scanning, no exploits, no packets. Fictional data. Outputs are fixes. |
| Windows-specific issues | Medium | Develop on Windows. CI on Linux. PowerShell and bash commands side by side. |
| Time | Medium | Thin version by Nov 27. Scope cuts above. |

## Demo video outline (1:50; the limit is 2:00)

| Time | Beat | On screen |
|---|---|---|
| 0:00 to 0:12 | Problem | July 2026 CISA alert headline: "100+ water systems… PLCs on cellular modems". "Small utilities have no security team and no cloud on the plant network." |
| 0:12 to 0:20 | Theme | "Every path to your PLCs. One file. No internet." Pull the network cable (literally) or show Wi-Fi off. |
| 0:20 to 0:45 | Flow A in the CLI | `build`, then `paths --to critical` (3 paths, modem → chlorine PLC), then `explain` |
| 0:45 to 1:05 | Browser what-if | The paths glow red. Tick "remove FW-114" and "move MDM-02". Paths go 3 → 0 and required flows stay 20/20. |
| 1:05 to 1:30 | Agent | Claude gets a new advisory, asks the graph, proposes a fix. **One proposal fails verification** ("would stop HMI-01 → PLC-07 Modbus"). The good one is approved by a human. |
| 1:30 to 1:42 | Evidence | Scorecard: 100% planted paths found, 0 false alarms, graph agent vs. CSV agent accuracy and tokens |
| 1:42 to 1:50 | Close | `data/fernhollow.rl` on GitHub, `relate info`. Repeat the theme. |

## Final README order

1. Title with keywords (Relate, OT security, water, offline, attack paths) and the one-line theme
2. Video link, viewer link, headline scorecard
3. **Use case:** the 2026 alert, Sam's scenario, who benefits
4. **How it uses Relate:** single-file mode, why that mode, what the graph models (diagram)
5. Requirements and criteria map (from 03)
6. **Setup and run:** Windows and macOS/Linux, three commands to the first path
7. Ask an agent (MCP and the skill)
8. **Where the data lives:** `data/fernhollow.rl`, the JSON export, how to inspect it
9. Evaluation and scorecard (including the agent comparison)
10. Responsible use and limits, data sources and licences (CISA, MITRE attribution)
11. Built with (Relate features, third-party tools, AI tools), the AI disclosure and reused code

## Pre-submission checklist

- [ ] The theme line appears on the viewer, at the top of the README, and in the video.
- [ ] Every criterion maps to a feature a judge can find in under a minute (03).
- [ ] Measured numbers back the claim (the scorecard and the agent comparison).
- [ ] Human approval, an audit trail (`:Change`), and a limits and responsible-use section are in place.
- [ ] Every claimed Relate feature is wired in and visible: single file, Cypher paths, clone, transactions, MCP, skill, WASM, full-text.
- [ ] A cold start works on Windows and Linux. The offline CI job is green.
- [ ] The viewer works from local files with no internet.
- [ ] The commit history is steady from Nov 22 to Dec 10.
- [ ] Every README claim is true. Fictional data is labelled as fictional.
- [ ] MITRE attribution and copyright notice are included (if ATT&CK is used). No implied endorsement by Neo4j, CISA or MITRE.
- [ ] The repo is public, tagged `relate` and `relate-neo4j-hackathon`, and visible at github.com/topics/relate.
- [ ] The repo has an Apache-2.0 LICENSE and a `.env.example`, and no secrets are in its history.
- [ ] Every Devpost field is filled in: title, a description of "what connects to what", the repo, the video (plays logged out), screenshots, the Relate features used, third-party tools, an AI disclosure and a reused-code disclosure.

## After the event

Keep the repo public and tagged through Dec 17. After the winners are announced, compare our entry with theirs on theme, evidence, criteria coverage, presentation and effort, and write down the lessons. There is nothing to tear down: we use no cloud resources beyond GitHub Pages.
