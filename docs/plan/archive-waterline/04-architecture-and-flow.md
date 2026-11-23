# 04 · Architecture, inputs, graph model, flows and UI

## Big picture

```
 INPUTS (files the utility already has)        BUILD (Python + relate-db)            STORE                  SURFACES
 ─────────────────────────────────────          ──────────────────────────            ─────                  ────────
 assets.csv        (inventory export)  ─┐                                                                    ┌─ CLI: waterline <cmd>      (engineer)
 firewall_rules.csv (FW export)         ├─► parse ─► normalise ─► compute reach ─► data/fernhollow.rl ──────┼─ MCP: relate serve --mcp   (agents)
 networks.csv      (VLANs, subnets)     │                         (rule → which                              ├─ Browser: web/index.html   (viewer)
 processes.yaml    (PLC → process)      │                          subnet can reach        │                 └─ Eval: waterline scorecard (KPIs)
 required_flows.yaml (must keep working)│                          which service)          │
 CISA CSAF advisories (subset, JSON) ───┤                                                  ├─► relate clone → scratch .rl  (what-if, then deleted)
 CISA KEV list, ATT&CK for ICS (opt.) ──┘                                                  └─► export → web/graph.cypher   (browser)
```

Everything runs on one laptop with the network unplugged.

## Inputs

| Input | Format | Size (fictional plant) | Notes |
|---|---|---|---|
| Asset inventory | CSV, shaped like a typical inventory export | ~150 assets | id, type (PLC, HMI, EWS, historian, switch, firewall, modem, VPN), vendor, model, firmware, IPs, zone, criticality |
| Firewall rules | CSV (vendor-neutral: src, dst, port, proto, action, comment, expires) | ~90 rules across 3 firewalls | Includes "temporary" rules with expiry dates |
| Networks | CSV: subnet, VLAN, zone, Purdue level | ~15 subnets, 6 zones | Zones: Internet, Office (IT), DMZ, Supervisory (L2), Control (L1), Safety |
| Process map | YAML: PLC → process → impact | ~10 processes | e.g. chlorine dosing = safety-critical |
| **Required flows** | YAML: flows that must keep working | ~20 flows | e.g. HMI-01 → PLC-07 Modbus/TCP 502. Used to check fixes. |
| CISA advisories | CSAF 2.0 JSON from cisagov/CSAF | ~30 to 60 advisories for the plant's vendors | Affected products and version ranges, CVEs, CVSS |
| CISA KEV (optional) | JSON | Filtered to matching CVEs | Marks "exploited in the wild" |
| ATT&CK for ICS (optional) | STIX 2.1 JSON | Techniques only | Labels path steps, e.g. "Remote Services", "Exploitation of Remote Services" |
| Runtime | CLI arguments, approvals, agent questions over MCP | — | — |

**Planted problems** in the fictional plant, with known answers (05): a cellular modem directly on the control VLAN, an expired temporary vendor rule still active, a dual-homed engineering workstation, an any-to-any rule hidden in a DMZ, a PLC on vulnerable firmware reachable only through two hops, and a decoy vulnerable PLC that is **not** reachable (to test for false alarms).

## Graph model

```
(:Zone {name, purdue_level})
   ▲ IN_ZONE
(:Subnet {cidr, vlan})
   ▲ ON
(:Interface {ip, mac}) ◄─HAS_INTERFACE─ (:Asset {id, type, vendor, model, firmware, criticality})
                                           ├─[:EXPOSES]─► (:Service {port, proto, name})      e.g. 502 Modbus, 44818 EtherNet/IP, 3389 RDP
                                           ├─[:RUNS]────► (:Product {vendor, model, firmware})
                                           └─[:CONTROLS]─► (:Process {name, impact})           e.g. chlorine dosing (safety-critical)
(:Rule {id, fw, action, comment, expires, temporary}) ─[:FROM]─► (:Subnet | :Asset)
                                                      ─[:TO]───► (:Subnet | :Asset)
                                                      ─[:PORT]─► (:Service)
(:Subnet|:Asset) ─[:CAN_REACH {port, via_rule}]─► (:Service)    derived at build time from rules plus routing
(:Advisory {id, title, published, cvss}) ─[:AFFECTS {versions}]─► (:Product)
(:Advisory) ─[:CITES]─► (:Vuln {cve, kev})  ─[:ENABLES]─► (:Technique {attack_id, name})   (optional)
(:RequiredFlow {id, why}) ─[:FROM]─► (:Asset) ─[:TO]─► (:Service)
(:Proposal {id, by, kind, verified, reason}) ─[:CHANGES]─► (:Rule | :Asset)
(:Change {at, actor, action}) ─[:APPLIED]─► (:Proposal)                                     audit trail
```

Indexes: a full-text index on `Advisory.title`, `Product.model` and `Asset.model`, so "micrologix" finds everything. A vector index is **optional** (semantic search over advisory text). It isn't needed for core value, so we avoid shipping an embedding model.

## Storage mode: single file (`data/fernhollow.rl`)

For the README's "Why this mode":

1. **The use case is "carry it to an offline site".** One file copies to a USB stick, can be checksummed and archived per site visit.
2. **Clone-to-verify:** `relate clone fernhollow.rl scratch.rl` makes a throwaway copy for each what-if or agent proposal, deleted afterwards.
3. **Safety:** the main file is opened `--read-only` for agents and viewing, and only `waterline review` writes to it.
4. **Inspectability for judges:** CI also writes a JSON-codec copy to `exports/fernhollow-json/` (via `relate clone --to-snapshot-format json`), so the graph is readable on GitHub without installing anything.

The trade-off we'll document: a `.rl` file refuses read-only opens while a writer holds it, so writes are short and done by one command.

## The seven core questions

| # | Question | How it works, in words |
|---|---|---|
| Q1 | **Exposure paths:** can anything in Internet, Office or Vendor reach a critical PLC service? | Path search from outside zones along `CAN_REACH` and multi-homed assets, ending at a Service on an Asset that `CONTROLS` a safety-critical Process |
| Q2 | **Advisory impact** | Advisory → `AFFECTS` → Product (version in range) ← `RUNS` ← Asset, then Q1 restricted to those assets |
| Q3 | **Choke points** | Count Q1 paths through each Rule or Asset, then rank them |
| Q4 | **Zone violations** | Assets with interfaces in two zones more than one Purdue level apart, and rules jumping from L4 to L1 |
| Q5 | **Stale access** | Temporary rules past `expires` that still allow traffic |
| Q6 | **What-if** | Clone, apply the change, re-run Q1 and the RequiredFlow checks, then report paths closed and flows broken |
| Q7 | **Explain** | Print a path hop by hop: asset, interface, subnet, rule ID, port and process |

## User flows

### Flow A: "The CISA alert just came out" (primary, Sam at Fernhollow)

1. `waterline build` builds the graph from today's exports. This happens on an office PC or an offline laptop.
2. `waterline paths --to critical` finds 3 exposure paths. The worst is cellular modem MDM-02 → PLC-07 (chlorine dosing), with no firewall.
3. `waterline explain P-1` shows the hop-by-hop proof.
4. `waterline chokepoints` says removing FW-114 plus moving MDM-02 behind FW-1 closes all 3.
5. `waterline whatif --remove-rule FW-114 --move MDM-02:DMZ` reports 3 paths closed and 0 required flows broken.
6. `waterline report --md` produces a printable report for the plant manager or the state advisor.

### Flow B: the agent triages a new advisory (human in the loop)

1. Register the MCP server, read-only: `relate serve --mcp stdio --database data/fernhollow.rl --read-only`.
2. Ask: *"Advisory ICSA-26-… just dropped. Are we affected and what should we do?"*
3. The agent calls `get_schema` and `read_cypher`, finds 2 matching PLCs, and sees that 1 is reachable from the vendor VPN.
4. The agent writes a proposal through `waterline propose`, our small write wrapper. The proposal is **verified automatically on a clone**, so it carries `verified: true` with "closes 1 path, breaks 0 required flows".
5. Sam runs `waterline review`, approves it, and it's committed in one transaction with a `:Change` record.
6. If the agent proposes something that breaks a required flow, the clone check catches it, marks it `verified: false`, and says which flow it broke. **This is the "graph keeps the agent honest" beat.**

### Flow C: two agents at once

The triage agent writes proposals while a review agent marks old proposals as superseded. Both write through transactions. A conflict on the same proposal is retried rather than silently lost. This demonstrates Relate's safe shared state.

### Flow D: a judge or advisor views it in the browser

Open `web/index.html` (offline, all files local) or the GitHub Pages copy. It shows these tabs:

- **Map:** zones as swim-lanes.
- **Paths:** attack paths highlighted in red.
- **Advisories**
- **What-if:** tick "remove FW-114" and watch the paths disappear. This is in-memory and never touches the file.
- **Scorecard**

## UI

| Surface | Purpose | Notes |
|---|---|---|
| **CLI** (Python, Rich tables) | Main tool for the engineer | Every command has `--json` for agents and scripts |
| **Browser viewer** (static, Relate WASM, Cytoscape.js or similar, **all assets bundled locally, no CDN**) | Viewing, demo and what-if | Must open from a USB stick with no internet. See the risk in 06. |
| **MCP plus the agent skill** | Agents | Read-only. Writes only through `waterline propose`. |
| **Report** (Markdown → print) | Hand-off to a manager or advisor | Paths, fixes and verification results |

### Browser screen sketch

```
┌ Waterline ── "Every path to your PLCs. One file. No internet." ─── Fernhollow Water District (fictional) ┐
│ [Show exposure paths]  [Check an advisory]                                     Offline ●   File: 1.9 MB   │
├────────────┬──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Map        │  Internet │ Office (L4) │ DMZ (L3.5) │ Supervisory (L2) │ Control (L1) │ Safety              │
│ Paths  (3) │   ◉───────────────────────────────────── MDM-02 (cell) ──────────► PLC-07 ⚠ Chlorine dosing  │
│ Advisories │   ◉──── VPN ──► FW-114 (expired) ──► ENG-WS-03 ──────────────────► PLC-03                   │
│ What-if    │                                                                                              │
│ Scorecard  │  What-if:  ☑ remove FW-114   ☑ move MDM-02 to DMZ   →  paths 3 → 0   required flows OK 20/20 │
└────────────┴──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The first 10 seconds must show what it is, who it's for, and two obvious buttons.

## Repo layout (planned)

```
README.md                 official template + requirements map + scorecard + responsible use
LICENSE                   Apache-2.0
inputs/fernhollow/        fictional plant: assets.csv, firewall_rules.csv, networks.csv, processes.yaml, required_flows.yaml
inputs/public/            CISA CSAF subset, KEV subset, (ATT&CK ICS); SOURCES.md with URLs, dates, licences
data/fernhollow.rl        ★ the persistent Relate store (single file)
exports/fernhollow-json/  JSON-codec clone for reading on GitHub (generated by CI)
src/waterline/            Python package: build, queries, whatif, propose, review, report, CLI
queries/                  one .cypher file per core question (the cookbook)
web/                      offline browser viewer + graph.cypher export
eval/                     ground_truth.yaml, golden questions, agent-runs/, scorecard.md/.json
docs/                     schema.md, queries.md, plan/ (these files)
.github/workflows/        build, tests, offline test (no network), scorecard, Pages deploy
```

## Third-party tools (to disclose)

relate-db (Python), @relate/relate-wasm, Typer or Click plus Rich, a CSAF parser (or plain JSON parsing), a JS graph renderer, pytest, GitHub Actions and Pages. Data comes from CISA (CSAF, KEV) and MITRE ATT&CK for ICS, with attribution. For AI, Claude Code helps write code and docs, and Claude is the MCP agent in the demo.
