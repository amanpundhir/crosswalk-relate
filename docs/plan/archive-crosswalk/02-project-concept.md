# 02 · Project concept

## Working name: Crosswalk

**One-line theme:** *Prove a control once, satisfy every framework, and see exactly what breaks when evidence expires.*

Every screen, README section and video beat must support this sentence.

## The problem

A small SaaS company (20 to 200 people) gets asked by customers for SOC 2 first, then by a government buyer for NIST 800-171, and later for an AI-risk or privacy framework. Each framework is a list of hundreds of requirements. In practice:

- **The same work is proven many times.** One access-review control satisfies requirements in several frameworks, yet teams collect the same screenshot again for each audit, because the links between frameworks live in spreadsheets.
- **Nobody can answer "what breaks if...?"** When an evidence item expires, a system is retired or the person who owns 14 controls leaves, the impact on each audit is invisible until the auditor finds it.
- **Mapping is slow, expert work.** Deciding which requirements a new internal control satisfies means reading hundreds of requirement texts.

These are **many-to-many relationship questions**: framework ↔ requirement ↔ control ↔ evidence ↔ system ↔ owner. Spreadsheets flatten them, and a graph answers them in a single traversal. That is the core of "Context, connected".

## Who it is for

| User | What they get |
|------|---------------|
| **Security or compliance lead** at a small SaaS company (the primary user) | Coverage per framework, the gap list, which evidence to reuse, and expiry risk before audit season |
| **Control owners** (engineers, IT, HR) | "Which controls do I own, which evidence of mine expires soon, and which audits depend on it?" |
| **Auditors** | A path for each requirement, from requirement to control to evidence with dates, that they can verify |
| **AI agents** (a compliance copilot, Claude Code) | A graph to query over MCP, so answers come from real relationships rather than guesses |

## Industry

**Governance, risk and compliance (GRC) within cybersecurity.** This is a real and growing market: SOC 2, ISO 27001, NIST CSF, NIST 800-53 and 800-171, CMMC, and new AI regulations. Commercial tools do this behind paid SaaS. We show that it can run locally, in one inspectable store, with open public frameworks.

## Does it need to have an impact on users? Yes: "Usefulness" is 20 points

The impact we will **show, not claim**:

1. **Less duplicated work.** The evidence reuse ratio is the number of requirements satisfied per evidence item, measured across frameworks.
2. **Faster answers.** A question like "are we ready for 800-171?" goes from a manual spreadsheet review to a single command in seconds.
3. **Fewer audit surprises.** The expiry blast radius lists the affected audits 30 days ahead.
4. **Faster mapping.** Hybrid search suggests mappings, and their quality is scored against NIST's official crosswalk.

All four are KPIs in [05](05-kpis-and-evaluation.md).

## What connects to what (for the Devpost description)

> Frameworks contain requirements. NIST's official crosswalk links requirements across frameworks. A company's controls satisfy requirements, evidence proves controls, controls apply to systems, people own controls, and audits scope frameworks and request evidence. Because it is a graph, one traversal answers "what breaks if this evidence expires?" and "how much of a new framework do we already meet?"

## Data (public and fictional only)

| Input | Source | Licence | Status |
|-------|--------|---------|--------|
| NIST SP 800-53 Rev 5 controls | NIST OSCAL content (JSON) | US government work, public domain | **Verify on day 1** |
| NIST CSF 2.0 subcategories | NIST CSF 2.0 reference data | Public domain | **Verify on day 1** |
| NIST SP 800-171 Rev 3 requirements | NIST | Public domain | **Verify on day 1** |
| Official crosswalk (CSF 2.0 ↔ 800-53, 800-171 ↔ 800-53) | NIST CPRT / OLIR mappings | Public domain | **Verify on day 1**. This is our ground truth. |
| The company pack: controls, evidence, systems, people, audits | We write it. A fictional 40-person SaaS company, "Harbor & Pine" | Ours, Apache-2.0 | To do |

**Not included:** the text of ISO 27001 or of the SOC 2 criteria (copyrighted), and any real company or real people. The README can mention that ISO and SOC 2 mappings would plug into the same graph model.

## Why this idea can win

- **Relate does the heavy lifting (30 points).** Coverage, crosswalk inference and blast radius are multi-hop traversals. Hybrid search does the mapping suggestions. MCP serves agents, WASM serves the browser, and transactions keep human approval safe. Every Relate surface does a real job.
- **Free ground truth for evidence.** NIST's official mappings let us *measure* suggestion quality, which most entries cannot.
- **An open lane.** About 108 tagged repos exist, and none covers compliance crosswalks. Neighbours such as casefold (KYC law), slowest-link (continuity plans) and changetrail (document change impact) are different problems.
- **Judges can run it.** No API keys and no cloud: clone, `pip install`, one command. The store is committed.

## Alternatives considered

| Idea | Why not |
|------|---------|
| Agent memory graph | The most crowded lane, with 12+ tagged repos |
| Course prerequisite and degree planner | Useful and easy, but a weaker "real problem" story, and judges have seen it in many graph demos |
| Power or water grid cascade twin | Strong graph story, but public topology data is hard to obtain and licence |
| Code or change-impact graph | Crowded, with 7+ tagged repos |

## Out of scope (say so in the README)

- Crosswalk is not legal or audit advice, and it does not certify compliance.
- No real company data, no SaaS integrations (Jira, AWS and so on), and no multi-tenant hosting.
- Suggested mappings are **proposals until a human approves them**.
