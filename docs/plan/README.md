# Planning pack: Relate by Neo4j Hackathon

These are planning documents only. No code exists yet. Read the files in order.

| # | File | What it answers |
|---|------|-----------------|
| 0 | [00-hackathon-brief.md](00-hackathon-brief.md) | What the hackathon is, the dates, what to submit and how entries are judged |
| 1 | [01-relate-primer.md](01-relate-primer.md) | What Relate is and which of its features we use |
| 2 | [02-project-concept.md](02-project-concept.md) | The idea, the agents and their rules, the industry, the users, the impact and honest positioning |
| 3 | [03-criteria-map.md](03-criteria-map.md) | Each judging criterion, including agent use, mapped to a feature a judge can point at |
| 4 | [04-architecture-and-flow.md](04-architecture-and-flow.md) | Inputs, the graph model (facts plus agent memory), storage mode, agent tools, the claim checker, flows and UI |
| 5 | [05-kpis-and-evaluation.md](05-kpis-and-evaluation.md) | KPIs: agent reliability, mapping quality, guardrails, correctness and impact |
| 6 | [06-build-plan.md](06-build-plan.md) | A day-by-day plan to Dec 11, risks, the video outline and the submission checklist |

## The plan in five lines

- **Project:** *Crosswalk*, an audit-prep agent for small SaaS teams. It runs on a compliance graph: NIST frameworks and the official crosswalk between them, plus the company's controls, evidence, systems, owners and audits.
- **Theme:** "An audit-prep agent that answers with receipts. Every claim is a path in the graph, from requirement to control to evidence."
- **Agent core:**
  - Four roles: audit-prep, mapper, evidence and auditor packet.
  - Agents read through MCP and can only write *proposals*.
  - A **claim checker** re-runs every cited path, and a **proposal verifier** checks every change.
  - Human decisions are stored in the same graph, so agents don't repeat a rejected suggestion.
- **Relate usage:**
  - A directory store (JSON codec). Several agents need to read while one writes.
  - Cypher path queries and hybrid vector plus full-text search.
  - Transactions so concurrent agents don't overwrite each other.
  - Relate's MCP server plus our narrow MCP server, the agent skill, and a WASM explorer.
- **Headline moments:**
  - **The live catch:** the agent confidently says "MFA is covered". The graph shows on screen that the evidence expired and one mapping is only proposed. `crosswalk demo live-catch` replays it without an AI key.
  - **One command to enable agents:** `crosswalk agent setup`.
  - **Real control wording** from open-source policy templates. Only the company's people, systems and dates are fictional.
  - **"Why not Vanta?"** answered in one line in the README.
- **Scope:** all four agents, CSF 2.0 and the two-agent demo stay in. Only polish items are on the cut list.
- **Evidence:**
  - The same agent with spreadsheets vs. with the graph vs. with the graph and the claim checker, measured on accuracy, wrong claims shown and tokens.
  - Mapping quality scored against NIST's official crosswalk.
  - Guardrail catch rates and a repeat-rejection rate.
  - The core runs with no API key.

## Facts checked on 2026-11-22

- Relate's current release is **1.2.0** (2026-11-20), Apache-2.0.
- The deadline is **Fri Dec 11, 2026, 6:00 PM PST**, 19 days from now.
- Neo4j's hackathon post also scores **how fully we use AI and agent capabilities**. It asks entries to show that connected context makes an agent more reliable.
- Paid tools (Vanta, Hyperproof) and a free one (crosswalker) already do framework crosswalks. Our difference is an open, local, inspectable graph, plus agents whose answers are checked and whose accuracy is measured.
