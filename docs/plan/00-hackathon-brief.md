# 00 · Hackathon brief

## What it is

The **Relate by Neo4j Hackathon** is a month-long online contest on Devpost (relate.devpost.com). It celebrates the launch of **Relate**, Neo4j's open-source embedded graph database, at NODES 2026.

The challenge is called **"Context, connected"**. Build something that shows how connected data helps agents, apps or people find and use the relationships that matter.

| Item | Detail |
|------|--------|
| Sponsor | Neo4j, Inc. |
| Contest period | Nov 11, 2026, 6:00 PM PST to **Dec 11, 2026, 6:00 PM PST** |
| Judging | Dec 12 to Dec 16 |
| Winners announced | Dec 17 |
| Team size | 1 to 4 people, one prize per entry |
| Prizes | 1st Mac Studio M5 Max, 2nd Mac mini M6 32 GB, 3rd Mac mini M6 16 GB |
| Judges | Eight Neo4j staff from product, developer relations and engineering (Michael Hunger, ABK, William Lyon, Oskar Hane, Yaru Lin, Kate Smith, Jennifer Reif, Stephen Chin) |

## The outcome they expect

A **public GitHub repo** that a judge can clone and run, and then see a real Relate graph, without asking us anything. The project must make **meaningful** use of Relate. Entries that are only prompts or AI-generated text, with no running Relate integration, are rejected.

### Required submission items

| # | Item | Our plan |
|---|------|----------|
| 1 | Title and description: the use case and what connects to what | Devpost text and the top of the README |
| 2 | Public GitHub repo with a setup and usage README | Follows the official README template (below) |
| 3 | GitHub topic `relate` (required), plus `relate-neo4j-hackathon` (recommended) | Add on day 1 so it is never forgotten |
| 4 | A persistent Relate store judges can inspect | Directory store at `data/crosswalk/` (JSON codec), committed |
| 5 | Working code with Relate actually running | CLI, MCP server and browser explorer |
| 6 | Demo video, 1 to 2 minutes, viewable without a login | YouTube unlisted, 1:50 |
| 7 | A statement of the Relate features, third-party tools and AI tools used | A "Built with" section in the README and on Devpost |
| 8 | Disclosure of significant AI use | Say that Claude Code helped write code and docs |
| 9 | Disclosure of reused code or libraries | List them in the README |

### The README template they gave (must be followed)

```
# Project name
One-line pitch.
## Use case
## How it uses Relate
- Mode: in memory | directory | single file
- Why this mode:
- What the graph models:
## Setup and run
## Where the data lives
```

The README must answer one question directly: **how are we using Relate, and why?** It must name the storage mode and justify it.

## How it is judged

Devpost lists weighted criteria. The rules call them "weighted equally", but the Devpost points are more specific, so we plan against the points.

| Criterion | Points | What it really means |
|-----------|--------|----------------------|
| Relate and connected context | **30** | The graph is central to the use case, not decoration. A judge can easily follow the instructions, run it and explore it. |
| Functionality and completeness | **25** | The core use case works end to end. |
| Usefulness | **20** | A real problem for a named user, and the project shows who benefits. |
| Documentation and reproducibility | **15** | The README explains the project and how to try it. |
| Creativity | **10** | An original idea or an inventive use of Relate. |

**Takeaway:** 70 of 100 points go to "the graph does real work", "it works" and "it helps someone". Creativity is worth only 10, so a sound, useful idea that runs perfectly beats a clever one that half works.

**Extra from Neo4j's own hackathon announcement post:** it also lists *"how fully you leveraged AI and agentic capabilities"* as a criterion. It asks entrants to "show us how connected context makes an agent more reliable". It also mentions a separate **public vote** for a community favourite. So our entry must include a real agent flow, not just a graph tool. (See 02 and 03.)

## Hard rules to keep in mind

- The project must be **started on or after Nov 11, 2026**. Reused code must be disclosed.
- The repo must stay **public and tagged** until winners are announced on Dec 17.
- **No real personal data** about other people. Use fictional or public data only.
- **Respect licences** for datasets. Neo4j advises against sensitive, regulated or production data.
- Use the Relate and Neo4j names only to identify the product. Do not suggest that Neo4j endorses the project.
- Some Relate features are experimental and may break. Prefer stable features (see 01).
- An open-source licence (MIT or Apache-2.0) is encouraged. We will use Apache-2.0 to match Relate.
