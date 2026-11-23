# 06 · Build plan, risks, video and submission

Today is **Sun Nov 22, 2026**. The deadline is **Fri Dec 11, 6:00 PM PST**. Our own target is to submit by **Thu Dec 10** and keep one day of buffer.

Rule from the playbook: a **thin end-to-end version first**, evaluation alongside the features, and **at least 20% of the time for presentation** (here, Dec 7 to 10).

## Milestones

| Dates | Milestone | Done when |
|-------|-----------|-----------|
| **Nov 22 to 23** | Setup and data check | Public repo created with topics `relate` and `relate-neo4j-hackathon`, Apache-2.0 licence, these plan docs committed. NIST files downloaded and licences recorded in `inputs/nist/SOURCES.md`. Relate CLI and `relate-db` installed and `RETURN 1` works. |
| **Nov 24 to 26** | **Thin end-to-end version** | Ingest of 800-53 plus 800-171 plus the crosswalk plus a small company pack into `data/crosswalk/`. `crosswalk coverage` prints a real result. Store committed. |
| **Nov 27 to 29** | Core questions | Q1 to Q4, Q6 and Explain, as `.cypher` files plus CLI commands. Full company pack with planted scenarios. A pytest for each planted fact. |
| **Nov 30 to Dec 2** | Hybrid suggestions plus evaluation | Embeddings precomputed, vector and full-text indexes, manual WRRF fusion, graph re-rank. `crosswalk scorecard` with the ablation. CI running. |
| **Dec 3** | Human-in-the-loop plus audit trail | `PROPOSED` edges, `crosswalk review` approving through transactions, `:Change` nodes, bookmarks shown. |
| **Dec 4 to 5** | Browser explorer | Export `graph.cypher`, WASM loads it, Coverage, Blast and What-if tabs, Scorecard tab, deployed to GitHub Pages. |
| **Dec 6** | Agents | Skill install, MCP read-only server, golden questions run with Claude Code and recorded, two-agent transaction demo. |
| **Dec 7 to 8** | Docs | README in the official template order, schema and query cookbook, limits and responsible use, "Built with" plus the AI disclosure, screenshots. |
| **Dec 9** | Video | Record and edit 1:50, upload unlisted, check it plays logged out. |
| **Dec 10** | Freeze and submit | Cold-start test on a clean Windows machine and Linux (or a container). Run the pre-submission checklist. Submit on Devpost. |
| **Dec 11** | Buffer | Fixes only. No new features. |

**Scope cuts if behind (in this order):** CSF 2.0 (keep 800-53 and 800-171), the graph re-rank, the two-agent demo, browser What-if (keep a read-only view). **Never cut:** the committed store, the README template, the scorecard, the cold-start test.

## Commit habit

Small commits every day from Nov 22. A steady history shows sustained effort, and rule 3 requires work to start within the contest period.

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| NIST file formats or licences differ from what we expect | Medium | Check on day 1. Fall back to the 800-53 ↔ 800-171 mapping only. |
| Relate preview features change or break | Medium | Use only stable features. `COMBINE` is optional. |
| The WASM build cannot open our store | Known | Export a Cypher script. The browser copy is in memory only (documented). |
| Embedding model download is too big or slow for judges | Medium | Ship precomputed embeddings in the store. Query-time embedding is optional, with a full-text fallback. |
| Single-writer lock confuses judges | Low | MCP and explorer export run `--read-only`. Error messages say what to do. |
| Windows-specific path or installer problems | Medium | Test on Windows (our machine) **and** Linux in CI. Give PowerShell and bash commands side by side. |
| Store grows too large for git | Low | Keep it under 25 MB. Round embeddings. Use the Parquet codec only if needed (and document it). |
| A judge thinks we claim to certify compliance | Low | A clear "not audit advice" note, with suggestions marked as proposals. |
| Time runs out | Medium | Thin version by Nov 26. Scope cuts above. |

## Demo video outline (1:50, the limit is 2:00)

| Time | Beat | On screen |
|------|------|-----------|
| 0:00 to 0:12 | Problem plus theme | "Three frameworks, hundreds of requirements, the same screenshot collected three times." Theme line. |
| 0:12 to 0:25 | What connects to what | Schema diagram animating in: framework, requirement, control, evidence, system, person, audit |
| 0:25 to 0:50 | Flow A in the CLI | `coverage` 78%, then `adopt` "21 gaps already met through the crosswalk", then `blast --days 30` |
| 0:50 to 1:10 | Browser what-if | Expire EV-044, coverage drops, the blast path is highlighted |
| 1:10 to 1:25 | Suggest plus human approval | `suggest`, then `review` approves, a transaction bookmark, coverage updates |
| 1:25 to 1:40 | Agent over MCP | Claude answers "which audits are at risk if Dana leaves?" with the real path |
| 1:40 to 1:50 | Evidence plus close | Scorecard: hybrid versus baselines, reuse ratio, `data/crosswalk/` on GitHub. Repeat the theme. |

## Final README order (playbook plus official template merged)

1. Title with keywords, plus the one-line theme
2. Live explorer link, video link, headline scorecard table
3. **Use case** (Maya's scenario, who benefits)
4. **How it uses Relate:** mode (directory, JSON codec), why this mode, what the graph models (diagram)
5. Requirements / criteria map (from 03)
6. **Setup and run:** Windows and macOS/Linux, three commands to the first result
7. Ask an agent (MCP plus skill)
8. **Where the data lives:** `data/crosswalk/`, plus how to inspect it
9. Evaluation and scorecard
10. Limits and responsible use, data sources and licences
11. Built with (Relate features, third-party tools, AI tools), plus the AI disclosure

## Pre-submission checklist

- [ ] The theme line is on the explorer landing view, at the top of the README, and in the video.
- [ ] Every criterion maps to a feature a judge finds in under a minute (03).
- [ ] At least one measured number backs the core claim (the scorecard).
- [ ] Human approval of AI and search suggestions, an audit trail, and a limits section are all present.
- [ ] Every Relate feature we claim is wired in and visible.
- [ ] The cold start works on Windows and Linux from the README alone.
- [ ] The explorer loads on GitHub Pages from a cold browser.
- [ ] The commit history is steady from Nov 22 to Dec 10.
- [ ] Every README claim is true.
- [ ] The repo is public, with topics `relate` and `relate-neo4j-hackathon`, and it appears at github.com/topics/relate.
- [ ] Apache-2.0 LICENSE, `.env.example` (even if empty), and no secrets in the history.
- [ ] Devpost fields are complete: title, description ("what connects to what"), repo link, video link (plays logged out), screenshots, Relate features used, third-party tools, AI disclosure, reused-code disclosure.

## After the event

Keep the repo public and tagged through Dec 17. After winners are announced, compare our entry with the winners on theme, evidence, criteria coverage, presentation and effort, and write down the lessons. There are no cloud resources to tear down (GitHub Pages only).
