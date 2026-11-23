# 02 · Project concept

## Working name: Waterline

**One-line theme:** *Every path to your PLCs, in one file, on one laptop, with no internet. Each answer is a path you can check.*

Every screen, README section and video beat must support this sentence.

(The earlier Crosswalk idea is kept in [archive-crosswalk/](archive-crosswalk/).)

## The problem, in plain words

A **PLC** (programmable logic controller) is the small computer that runs a pump, a valve or a chemical dosing unit. In a water plant, PLCs decide how much chlorine goes into drinking water.

In 2026 this became a front-page problem:

- In **July 2026, CISA reported attacks on more than 100 internet-exposed water-sector systems.** Most were PLCs wired straight to a **cellular modem** that someone added for remote monitoring ([CISA alert via govdelivery](https://content.govdelivery.com/accounts/USDHSCISA/bulletins/422e63c), [BleepingComputer](https://bleepingcomputer.com/news/security/cisa-warns-of-cyberattacks-disrupting-us-water-utilities), [SecurityWeek](https://www.securityweek.com/cisa-urges-water-sector-to-protect-ot-after-coordinated-attacks-on-plcs/amp/)).
- **Small utilities have no security staff.** They depend on outside help ([BeyondTrust](https://www.beyondtrust.com/blog/entry/water-wastewater-cyberattacks-state-local-response), [LevelBlue](https://www.levelblue.com/blogs/levelblue-blog/practical-cybersecurity-for-small-water-utilities-5-steps-to-reduce-operational-risk)).
- Many sites **believe they are air-gapped** (fully cut off) when they are not ([runZero](https://www.manufacturing.net/cybersecurity/news/22966305/expanded-ot-intelligence-and-attack-path-mapping)).
- The plant network is often **not allowed** to run new servers or reach the cloud, so cloud security tools can't be used there.

Today an engineer answers *"can anything outside reach the chlorine PLC?"* by reading an asset spreadsheet, a firewall rule export and a network diagram **side by side, by hand**. One forgotten rule ("temporary vendor access, 2023") or one extra modem breaks that answer, and nobody notices.

**This is a path question:** outside → modem, VPN or office network → firewall rule → engineering laptop → PLC → chemical process. Spreadsheets can't follow paths. A graph can.

## What Waterline does

It takes the files a utility **already has** and builds one connected graph in a **single Relate file**: the asset list, the firewall rules, the network and VLAN map, which PLC controls which process, and public CISA advisories. That file can travel on a USB stick to an offline laptop.

It then answers, offline:

| Question | Example answer |
|---|---|
| **Can anything outside reach a critical PLC?** | "Yes. Cell modem MDM-02 → PLC-07 (chlorine dosing), port 44818, no firewall in between." |
| **A new CISA advisory came out. Does it affect us?** | "2 of your PLCs run the affected firmware. 1 of them is reachable from the vendor VPN." |
| **Which single fix closes the most paths?** | "Removing rule FW-114 (temporary vendor access, expired 2024) closes 11 of 14 paths." |
| **Is that fix safe?** | "Yes. HMI-01 → PLC-07 Modbus still works, because that flow is required for operations." |
| **Where does reality break our zone design?** | "ENG-WS-03 has a leg in both the office and control networks (dual-homed)." |
| **Show me the proof** | The full hop-by-hop path, with the firewall rule IDs and ports, printed for the engineer |

## The agent part (the hackathon scores AI and agent use)

Neo4j's hackathon post asks to *"show how connected context makes an agent more reliable."* Waterline's agent flow:

1. **The triage agent** reads a new CISA advisory, asks the graph over MCP which assets match and what can reach them, and writes a short risk note.
2. It **proposes a fix**, such as "remove rule FW-114" or "move MDM-02 behind FW-1", as a `PROPOSED` change.
3. **The graph checks the agent's work.** The fix is applied to a throwaway copy of the graph. Waterline re-runs the path queries and confirms the bad path is gone **and** no required operational flow broke.
4. **A human approves** before anything is written to the main file. Every change is recorded.

The point to show: **an agent with raw files guesses; an agent with the graph proves.** We measure both (05).

Waterline itself does **not** need an AI or internet to work. All core questions are plain graph queries. The agent is an extra layer: Claude over MCP in the demo, and any MCP-capable local model for a truly offline site.

## Who it's for

| User | What they get |
|---|---|
| **Operator or engineer at a small water utility** (primary) | "Are we exposed?" answered in seconds, offline, from their own files |
| **Contract integrator or OT consultant** visiting many sites | One file per site on a laptop. Clone it, try fixes, hand over a report. |
| **State or regional cyber advisor** helping small utilities, as CISA and EPA advisors do | A consistent, repeatable check they can run with each utility |
| **AI agents** (a triage copilot) | Facts about real connections instead of guesses |

## Industry

**Critical infrastructure / operational technology (OT) security**, starting with water and wastewater. The same model fits power substations, manufacturing lines and building automation.

## Impact on users (Usefulness, 20 points)

1. **Find hidden exposure before attackers do.** This is the exact failure behind the July 2026 attacks.
2. **Hours to minutes for advisory triage.** "Does this advisory affect us, and is it reachable?" becomes one command.
3. **Safer fixes.** Every proposed change is checked against the flows the plant needs, so a fix doesn't stop the pumps.
4. **Works where cloud tools can't:** offline, no server, no install on the plant network.

## Why Relate is the right tool (and not just a tool)

| Need | Why other options struggle | What Relate gives |
|---|---|---|
| Runs on an offline laptop or plant PC, with no server | Neo4j or other graph servers need installing and running, and IT may forbid that on OT | One binary or `pip` package, and one `.rl` file |
| Path questions ("reach", "through", "via") | SQL needs long recursive joins. Spreadsheets can't do it. | Cypher path patterns |
| A safe "what-if" sandbox | You'd have to copy a whole database server | `relate clone plant.rl scratch.rl`, test the change, then delete it |
| Agent access | Building a custom API takes time | `relate serve --mcp` exposes the graph to any MCP agent |
| Hand-off between people and sites | Database dumps are clumsy | A single file you can copy, check and archive |
| A no-install viewer | Desktop apps need installing | The WASM build runs in a browser from local files |

**Honest limits:** commercial OT platforms such as Tenable OT, Claroty and Nozomi do much more, like live traffic monitoring, but cost a lot and need servers. Free tools do parts: [ot-pcap-triage](https://pypi.org/project/ot-pcap-triage/) builds inventories from traffic captures, and [deadband](https://awesome.ecosyste.ms/projects/github.com%2Fjmeltz%2Fdeadband) matches firmware offline. Neither traces attack paths. Waterline is **not** a replacement for monitoring. It is a free, offline "map and check" tool for teams that have nothing today.

## Not taken yet

None of the ~108 repos tagged `relate` covers OT, ICS or plant networks. The closest neighbours are different: chokepoint-lab (maritime), blind-flange (piping work permits) and agent-trellis (general security intel).

## Data (public plus fictional only)

| Input | Source | Licence | Status |
|---|---|---|---|
| ICS security advisories | CISA's official CSAF 2.0 repo, [github.com/cisagov/CSAF](https://github.com/cisagov/CSAF). Machine-readable, covers ICS advisories back to 2017. | US government work. **Confirm on day 1.** | Use a subset matching the plant's vendors |
| Known-exploited flag | CISA Known Exploited Vulnerabilities (KEV) catalog | US government work. **Confirm.** | Adds `exploited_in_wild` to vulnerabilities |
| ICS attack techniques | MITRE ATT&CK for ICS, STIX 2.1 in `mitre-attack/attack-stix-data` | Free use, but MITRE's copyright notice must be reproduced and the name can't be used in product names ([terms](https://attack.mitre.org/resources/legal-and-branding/terms-of-use/)). **Check the repo LICENSE.** | Optional: label paths with techniques |
| The plant | **We create it:** "Fernhollow Water District (fictional)", about 150 assets across 6 zones, about 90 firewall rules, a VLAN map, process mapping, and a few cellular modems and vendor VPNs | Ours, Apache-2.0 | Includes **planted problems with known answers** |

**Real product names, fictional plant.** Assets use real PLC models and firmware versions so real advisories match. The plant, its people and its network are invented, and the README says so clearly.

## Responsible use (contest rule 10: nothing designed to attack)

- **Defensive only.** It reads inventory files the owner already has. **No scanning, no exploit code, no packet sending.**
- Outputs are written for defenders: which rule to remove, which modem to move.
- The demo uses fictional data only.
- Proposed fixes need human approval, and there is a "not a substitute for professional assessment" note.

## Ideas considered and why not

| Idea | Why not |
|---|---|
| Crosswalk (compliance graph) | Paid tools already exist, and the agent angle was weak. Archived. |
| Multi-agent task board | Useful, but partly taken and harder to show a clear user benefit |
| Codebase map for coding agents | Crowded (7+ entries) |
