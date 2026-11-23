# 04 · Architecture, inputs, graph model, flows and UI

## Big picture

```
 INPUTS                         BUILD (Python + relate-db)          STORE                     SURFACES
 ───────                        ──────────────────────────          ─────                     ────────
 NIST 800-53 (OSCAL JSON) ─┐                                                                 ┌─ CLI: crosswalk <cmd>  (people)
 NIST CSF 2.0              ├─► parse ─► normalise ─► embed ─► load ─► data/crosswalk/  ──────┼─ MCP: relate serve --mcp (agents)
 NIST 800-171              │                         (local    (one     (directory store,    ├─ Browser: WASM explorer (judges)
 NIST official crosswalk ──┤                          model,    txn per  JSON codec,         └─ Eval: crosswalk scorecard (KPIs)
 Company pack (YAML) ──────┘                          384-d)    batch)   committed)
                                                                              │
                                                                              └─► export: web/graph.cypher (for the WASM explorer)
```

## Inputs

| Input | Format | Approximate size | Notes |
|-------|--------|------------------|-------|
| Framework catalogs | JSON (OSCAL) and CSV/XLSX from NIST | About 1,200 to 1,500 requirements in total | Requirement ids, titles, text and the family hierarchy |
| Official crosswalk | CSV/XLSX from NIST | About 1,000+ mapping rows | Becomes `EQUIVALENT_TO` edges **and** the evaluation ground truth |
| Company pack: fictional "Harbor & Pine" | Hand-written YAML in `inputs/company/` | About 60 controls, 120 evidence items, 25 systems, 15 people, 3 audits | Includes **planted scenarios** with known answers (05) |
| User actions at runtime | CLI arguments, approvals, browser what-if clicks | — | Approvals are persisted, browser edits are not |
| Agent questions | Natural language through MCP | — | The agent writes Cypher, Relate returns a JSON envelope |

## Graph model

```
(:Framework {id, name, version})
   ▲ PART_OF
(:Family {id, name})                       e.g. "AC – Access Control", CSF "PR.AA"
   ▲ PART_OF
(:Requirement {id, framework, title, text, embedding[384]})
   ├─[:EQUIVALENT_TO {source:'NIST', relationship}]─(:Requirement)    official crosswalk
   ▲
   │ [:SATISFIES {status:'approved', approved_by, approved_at, score}]
   │ [:PROPOSED  {score, method:'hybrid', rank}]                       awaiting human review
(:Control {id, title, description, embedding[384], status})
   ▲ PROVES                         ─[:APPLIES_TO]─► (:System {name, criticality, data_class})
(:Evidence {id, kind, collected_at, expires_at, location})
(:Person {name, team, role}) ─[:OWNS]─► (:Control)   ─[:OWNS]─► (:Evidence)
(:Policy {id, title}) ─[:MANDATES]─► (:Control)
(:Audit {id, name, date}) ─[:SCOPES]─► (:Framework)    ─[:REQUESTS]─► (:Evidence)
(:Change {at, actor, action, detail}) ─[:CHANGED]─► (any node)        audit trail of approvals and edits
```

Indexes:

- A vector index on `Requirement.embedding`, with `WITH [framework]`, so suggestions can be filtered per framework.
- A full-text index on `Requirement.title, Requirement.text`.
- A full-text index on `Control.title, Control.description`, for agent keyword lookup.

## Storage mode: a directory store with the JSON codec

This goes into the README's "Why this mode" section:

1. **Judges can inspect it without installing anything.** `graph.json` is readable on GitHub.
2. **It is diffable.** A git diff between two commits shows exactly which mappings a human approved. That is the audit trail in the version history too.
3. **Readers can run next to a writer.** The MCP server and the explorer export run `--read-only` while `crosswalk review` writes. A `.rl` file refuses read-only opens while a writer holds it.
4. **The size is small.** About 3k nodes and 10k relationships, plus 384-d embeddings, is a few MB of JSON.
5. A `.rl` copy can be produced on demand with `relate clone` for anyone who wants one file.

The browser cannot open directory stores, so the build also **exports `web/graph.cypher`**, a script the WASM explorer runs into an in-memory graph.

## The six core questions (these drive every surface)

| # | Question | Traversal in words |
|---|----------|--------------------|
| Q1 | **Coverage:** which requirements of framework F have no approved, evidenced control? | Framework → requirements, minus those reached by an approved `SATISFIES` from a control with at least one unexpired `PROVES` |
| Q2 | **Adopt:** how much of a new framework do our current controls already meet? | Control → `SATISFIES` → requirement → `EQUIVALENT_TO`{1,2} → requirement in the new framework |
| Q3 | **Blast radius:** what breaks if evidence expires in N days? | Evidence (expiring) → controls → requirements → frameworks → audits, keeping only controls left with no other valid evidence |
| Q4 | **Reuse:** which evidence items do the most work? | Evidence → controls → requirements, counted by distinct framework |
| Q5 | **Suggest:** which requirements does this control probably satisfy? | Hybrid search of the control's text against requirements, filtered by framework, then written as `PROPOSED` edges |
| Q6 | **Owner risk:** whose departure hurts most? | Person → `OWNS` → controls → requirements, ranked by critical systems touched and the number of controls with no other owner |

Plus **Explain**: requirement ← control ← evidence, with dates, as auditor-ready Markdown.

## User flows

### Flow A: the compliance lead preparing for an audit (primary)

1. `crosswalk build` creates or updates the store from the inputs.
2. `crosswalk coverage --framework 800-171` returns 78% covered and 34 gaps, grouped by family.
3. `crosswalk adopt 800-171` shows that 21 of the gaps are already met through existing 800-53 controls via the crosswalk, and lists them for review.
4. `crosswalk blast --days 30` shows that 3 evidence items expire before the audit, which would drop 9 requirements across 2 audits.
5. `crosswalk explain 03.01.01 --md` produces an auditor-ready path document.

### Flow B: mapping a new control, with a human in the loop

1. Add a control to `inputs/company/controls.yaml`, or run `crosswalk control add`.
2. `crosswalk suggest CTRL-061 --framework 800-53 --k 5` returns ranked requirements, with score and method (vector, full text or fused).
3. They are stored as `PROPOSED` edges (not counted in coverage).
4. `crosswalk review` approves or rejects each one. Each approval runs in **one transaction** that turns the `PROPOSED` edge into `SATISFIES`, writes a `:Change` node and returns a bookmark.
5. Coverage updates immediately.

### Flow C: an agent answers a question (Claude Code over MCP)

1. `relate skill install --agent claude-code` (one time).
2. Register the MCP server: `relate serve --mcp stdio --database ./data/crosswalk --read-only`.
3. Ask: "Which audits are at risk if Dana leaves?" The agent calls `get_schema`, then `read_cypher`, and answers with the actual path.
4. Optionally, a second agent with write access proposes mappings while the first reads. Transactions keep them apart, and this is the "safe shared state" demo.

### Flow D: a judge explores in the browser (no install)

1. Open the GitHub Pages link. WASM loads `graph.cypher` in a couple of seconds.
2. Tabs: **Coverage**, **Adopt**, **Blast**, **Graph**, **Scorecard**.
3. **What-if:** click "expire this evidence" or "remove this person". The in-memory graph updates, and coverage and the blast view recompute live. A "Reset" button restores the original.

## UI

| Surface | Purpose | Notes |
|---------|---------|-------|
| **CLI** (Python, plus Rich tables) | The main working tool | Every command accepts `--json` (envelope-style) for agents and scripts |
| **Browser explorer** (static site, Relate WASM, a graph library such as Cytoscape.js or Sigma.js) | Judges, demo, what-if | No backend. Hosted on GitHub Pages. Read-only data plus in-memory edits. |
| **MCP plus the agent skill** | Agents | Read-only by default. Write mode is shown only in the two-agent demo. |
| **Scorecard page** (`eval/scorecard.md`, also a browser tab) | The KPIs | Regenerated by CI on every push |

### Browser screen sketch

```
┌ Crosswalk ── "Prove a control once, satisfy every framework." ───────── [Reset what-if] ┐
│ Frameworks: [800-53 ▾] [800-171 ▾] [CSF 2.0 ▾]   Audit: [800-171 assessment, Jan 15 ▾]   │
├──────────────┬───────────────────────────────────────────────────────────────────────────┤
│ Coverage     │  800-171: ███████████████░░░░ 78%   gaps 34   adopt-able 21               │
│ Adopt        │  ┌ Family ───────────── covered ─ gaps ┐   ┌ Graph ──────────────────────┐ │
│ Blast radius │  │ 03.01 Access Control   18/22   4     │   │ (Evidence)→(Control)→(Req)  │ │
│ Graph        │  │ 03.05 Identification    9/11   2     │   │  highlighted blast path     │ │
│ Scorecard    │  └──────────────────────────────────────┘   └─────────────────────────────┘ │
│              │  What-if: [Expire EV-044]  [Remove Dana]  → coverage 78% → 71% (−7 reqs)    │
└──────────────┴───────────────────────────────────────────────────────────────────────────┘
```

The first 10 seconds must show what it is, who it is for, and two obvious buttons: **"Show audit gaps"** and **"What breaks in 30 days?"**

## Repo layout (planned)

```
README.md               official template plus requirements map plus scorecard
LICENSE                 Apache-2.0
inputs/nist/            downloaded raw files, with a SOURCES.md listing URLs, dates and licences
inputs/company/         fictional company pack (YAML) plus planted-scenario notes
data/crosswalk/         ★ the persistent Relate store (directory, JSON codec)
src/crosswalk/          Python package: build, queries, CLI, eval
queries/                one .cypher file per core question (the documented cookbook)
web/                    WASM explorer plus graph.cypher export
eval/                   ground truth, golden questions, scorecard.md / scorecard.json
docs/                   schema.md, queries.md, plan/ (these files)
.github/workflows/      CI: build, test, scorecard, Pages deploy
```

## Third-party tools (to disclose)

relate-db (Python), @relate/relate-wasm, a local sentence-embedding model (a candidate is a small 384-d MiniLM-class model, to be checked for licence and size), Typer or Click plus Rich for the CLI, a JS graph renderer, pytest, GitHub Actions and Pages. For AI, Claude Code helps write code and docs, and Claude is an optional MCP client in the demo.
