# 03 · Criteria-to-feature map

For each criterion, a concrete feature a judge can find in **under a minute**. This table becomes the "Requirements map" section of the final README.

Devpost points: Relate and connected context 30, Functionality 25, Usefulness 20, Docs 15, Creativity 10. Neo4j's hackathon post also lists **"how fully you leveraged AI and agentic capabilities"**, so agent use gets its own section below.

## Relate and connected context (30)

| Feature | Relate capability | Where a judge sees it |
|---|---|---|
| **Exposure paths:** outside → … → critical PLC | Cypher variable-length and quantified path patterns over `CAN_REACH`, `HAS_INTERFACE` and `CONTROLS` | `waterline paths --to critical`, and the browser Paths tab |
| **Advisory impact:** advisory → firmware → asset → who can reach it → process at risk | Multi-hop traversal plus version-range matching | `waterline advisory ICSA-26-xxx-yy` |
| **Choke points:** the rule or asset that sits on the most paths | Path counting and aggregation | `waterline chokepoints` |
| **Zone violations:** dual-homed hosts, undocumented conduits | Pattern match across zones | `waterline zones --violations` |
| **Safe what-if:** test a fix on a copy | `relate clone` to a scratch `.rl`, write, re-query, delete | `waterline whatif --remove-rule FW-114` |
| **Approval that can't half-apply** | Transactions. Commit returns a bookmark. | `waterline review`, and the change log |
| **Agents ask the graph** | `relate serve --mcp stdio --read-only`, plus `relate skill install` | README "Ask an agent" section, and the video |
| **One portable file** | Single-file `.rl` store, committed | `data/fernhollow.rl`, `relate info --database data/fernhollow.rl` |
| **No-install viewer** | WASM build running fully from local files | `web/index.html` (also on GitHub Pages) |
| Advisory text search, e.g. "Rockwell MicroLogix" | Full-text index on advisory titles and products | `waterline search "micrologix"` |

## AI and agent use (called out in Neo4j's hackathon post)

| Feature | Proof |
|---|---|
| Triage agent: new advisory → risk note → proposed fix | Recorded agent session in the video, with the transcript in `eval/agent-runs/` |
| **Graph checks the agent:** every proposed fix is re-tested on a clone | The `verified: true/false` field on each proposal, plus the reason |
| Agent with graph vs. agent with raw CSVs: accuracy and tokens | `eval/agent-comparison.md` (05) |
| Two agents writing safely: triage agent plus change-review agent | Transaction conflict shown and resolved, in the demo |

## Functionality and completeness (25)

| Feature | Proof |
|---|---|
| One command builds the whole graph from raw files | `waterline build` recreates `data/fernhollow.rl` deterministically |
| Every README command works on a cold clone | Cold-start test on Windows plus Linux, in CI |
| **Works with the network switched off** | CI job runs everything inside a container with no network |
| Seven core questions answered | paths, advisory, chokepoints, zones, expired rules, whatif, explain |
| Clear errors | e.g. "storage locked: another program has the file open. Close it or use --read-only." |

## Usefulness (20)

| Feature | Proof |
|---|---|
| A real, current problem | README opens with the July 2026 CISA alert on exposed water PLCs (with links) |
| A named user and scenario | "Sam, the one-person IT and OT team at Fernhollow, hears about the alert on Monday morning…" |
| Measured impact | Scorecard: paths found, minutes to triage, paths closed by the top 3 fixes, required flows kept |
| A hand-off report | `waterline report --md` produces a printable findings report for the utility board or an advisor |

## Documentation and reproducibility (15)

| Feature | Proof |
|---|---|
| The official README template, in order | Mode: single file. Why: portable to offline sites. Graph model. Setup. Where the data lives. |
| Copy-paste quick start for Windows and macOS/Linux | Three commands to the first path |
| Schema diagram, query cookbook, data sources with licences | `docs/schema.md`, `docs/queries.md`, `inputs/SOURCES.md` |
| Scorecard published | `eval/scorecard.md` |
| Limits and responsible use | Defensive-only statement, fictional data, not a replacement for monitoring |

## Creativity (10)

| Feature | Why it's fresh |
|---|---|
| **A graph database that travels on a USB stick** to sites where servers and cloud aren't allowed | Uses Relate's embedded, single-file nature as the core feature, not a convenience |
| **Clone-to-verify** for agent proposals | Throwaway copies of the graph used to check AI output before a human sees it |
| An untouched domain (OT and water) in this hackathon | None of the ~108 tagged repos covers it |
