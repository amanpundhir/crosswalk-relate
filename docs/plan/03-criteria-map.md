# 03 · Criteria-to-feature map

Each judging criterion is paired with a concrete feature a judge can find in **under a minute**. This table becomes the "Requirements map" in the final README.

Points on Devpost:

| Criterion | Points |
|---|---|
| Relate and connected context | 30 |
| Functionality | 25 |
| Usefulness | 20 |
| Docs | 15 |
| Creativity | 10 |

Neo4j's hackathon post also lists **"how fully you leveraged AI and agentic capabilities"**, so agents get their own section below.

## Relate and connected context (30)

| Feature | Relate capability | Where a judge sees it |
|---|---|---|
| Coverage and gaps per framework | Multi-hop traversal from framework to requirement, through `SATISFIES`, to control, then `PROVES`, to evidence | `crosswalk coverage --framework 800-171`, browser Coverage tab |
| Adopt: coverage inherited through the NIST crosswalk | Quantified path patterns over `EQUIVALENT_TO` | `crosswalk adopt 800-171` |
| Expiry blast radius | Evidence → controls → requirements → frameworks → audits | `crosswalk blast --days 30`, browser Blast tab |
| Hybrid candidate search for mappings | Vector index + full-text index, fused with WRRF, filtered per framework | `crosswalk suggest CTRL-061` |
| **One graph holds both compliance facts and agent memory** | `:Proposal`, `:Claim`, `:Decision` nodes linked to the facts they cite | `crosswalk decisions`, plus the schema diagram |
| **Claim checking** | Re-run the cited path ids as Cypher before an answer is shown | `crosswalk check <answer.json>`, "✔ verified" badges in the video |
| Safe shared state for several agents | Transactions, retry on conflict, bookmarks | Two-agent demo and the change log |
| Agents query the graph directly | `relate serve --mcp stdio --read-only` + `relate skill install` | README section "Ask an agent" |
| Inspectable store | Directory store with the JSON codec, committed | `data/crosswalk/` on GitHub, `relate info` |
| No-install explorer | WASM, with in-memory what-if | GitHub Pages link |

## AI and agent use (from Neo4j's hackathon post)

| Feature | Proof |
|---|---|
| Four agent roles: audit-prep, mapper, evidence, auditor packet | `agents/` prompts plus skills, and transcripts in `eval/agent-runs/` |
| **The live catch** (the "wow" moment): the agent confidently makes a wrong claim, and the graph catches it on screen | `crosswalk demo live-catch` replays it, and it is the centre beat of the video (06) |
| **One-step agent setup** | `crosswalk agent setup` installs the Relate skill and registers both MCP servers |
| **Receipts or it didn't happen**: every claim cites paths and is checked | The claim-checker pass rate on the scorecard |
| Proposals are verified before human review | `verified` and `reason` fields on every `:Proposal` |
| Memory of human decisions | The repeat-rejection rate, measured (05) |
| **Agent with the graph vs. agent with spreadsheets**: accuracy, valid citations, tokens | `eval/agent-comparison.md` |
| Agents writing concurrently without clobbering | Conflict shown and resolved in the demo |

## Functionality and completeness (25)

| Feature | Proof |
|---|---|
| One command builds the whole graph | `crosswalk build` re-creates `data/crosswalk/` deterministically |
| Every README command works on a fresh clone | Cold-start test on Windows and Linux in CI |
| The core works with **no API key** | CI runs everything except the agent runs, with no secrets |
| Six core questions, plus explain | coverage, adopt, blast, reuse, suggest, owners, explain |
| The agent loop end to end | Question → cited answer → check → proposal → verify → human approve → coverage updates |
| Clear errors | e.g. "storage locked → another writer is open. Use --read-only or close it." |

## Usefulness (20)

| Feature | Proof |
|---|---|
| A named user and scenario | "Maya, security lead at Harbor & Pine, has an 800-171 audit in 6 weeks…" |
| Measured impact | Scorecard shows: agent accuracy with and without the graph, reuse ratio, inherited coverage, gaps flagged 30 days early |
| Auditor-ready output | `crosswalk explain <req> --md`, or the auditor-packet agent for a whole audit |
| Realistic inputs | Controls and policies come from real open-source policy templates. Only the company's people, systems and dates are fictional. |
| A one-line answer to "why not Vanta?" | Near the top of the README (02) |

## Documentation and reproducibility (15)

| Feature | Proof |
|---|---|
| The official README template, in order | Mode, why this mode, graph model, setup, where the data lives |
| Copy-paste quick start for Windows and macOS/Linux | Three commands to the first result. **One more command, `crosswalk agent setup`, enables the agents.** |
| Schema diagram, query cookbook, agent prompts | `docs/schema.md`, `docs/queries.md`, `agents/` |
| Published scorecard | `eval/scorecard.md` |
| Limits and responsible AI | Section in the README |

## Creativity (10)

| Feature | Why it's fresh |
|---|---|
| **One graph is both the knowledge and the agent's memory and audit trail** | Proposals, claims and decisions are first-class nodes beside the facts |
| **The claim checker**: agent answers are verified by re-running their own cited paths | Turns "trust me" answers into checkable ones. The live catch shows it happening: a confident wrong claim, caught by the graph in under a second, with the reason. |
| NIST's official crosswalk used as ground truth to grade the agent | Makes a compliance agent measurable |
