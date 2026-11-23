# 02 · Project concept: Crosswalk with an agent core

## Working name: Crosswalk

**One-line theme:** *An audit-prep agent that answers with receipts: every claim is a path in the graph, from requirement to control to evidence.*

**Supporting line:** *Prove a control once, satisfy every framework, and see what breaks before the auditor does.*

Every screen, README section and video beat must support the theme.

(Earlier versions are kept for reference: [archive-crosswalk/](archive-crosswalk/) holds v1, which had no agent core. [archive-waterline/](archive-waterline/) holds the offline OT idea.)

## The problem, in plain words

A small SaaS company gets asked by different customers for different security rulebooks (frameworks), such as NIST 800-53, NIST 800-171 and NIST CSF. Many rules across these rulebooks mean the same thing, but teams track them in spreadsheets. Vendor guides agree that once several frameworks overlap, mapping the relationships in a spreadsheet quickly becomes overwhelming, and spreadsheets can't link evidence to controls in both directions ([SmartSuite](https://www.smartsuite.com/what-is/what-is-control-framework-mapping), [Wolters Kluwer](https://wolterskluwer.com/en/expert-insights/managing-multiple-compliance-frameworks-efficiently)).

The results:

1. **The same screenshot gets collected three times**, once per audit.
2. **Nobody sees what breaks** when evidence expires or a control owner leaves.
3. **Mapping a new control takes days**: someone reads hundreds of rules by hand.

## Why an agent, and why it needs the graph

Teams now ask AI assistants things like "are we ready for 800-171?". A chatbot reading spreadsheets or PDFs **guesses**. It can't see that one screenshot expired, or that a mapping was rejected last week. It can't prove anything.

Neo4j's hackathon post asks entrants to *"show us how connected context makes an agent more reliable."* That is exactly Crosswalk's core:

> **The agent does the work. The graph keeps it honest.**
> Every answer must cite a path in the graph, and Crosswalk re-checks that path before showing the answer. Every proposed change is tested before a human sees it. Every human decision is stored in the graph, so the agent never repeats a rejected suggestion.

## What the agents do

| Agent | Job | Example |
|---|---|---|
| **Audit-prep agent** (main, chat) | Answers readiness questions with cited paths | "Are we ready for the Jan 15 800-171 audit?" → "78% covered, 34 gaps. 21 can be closed through existing 800-53 controls. 3 evidence items expire before the audit." Each number links to its paths. |
| **Mapper agent** | Proposes which requirements a new control satisfies | Hybrid search finds candidates. The agent reads them with graph context (sibling requirements, the NIST crosswalk, past rejections) and writes `PROPOSED` mappings with a reason. |
| **Evidence agent** | Watches expiry and owners, and drafts evidence requests | "EV-044 expires Dec 30 and is the only proof for 3 controls. Here is a drafted request to Dana." A human sends it. |
| **Auditor-packet agent** | Builds the proof document an auditor asks for, one section per requirement in the audit's scope | "Packet for the Jan 15 800-171 audit: 97 requirements (Rev 3). Each has its control, its evidence with dates and its claim-check status. 3 are marked ⚠ with the reason." Every line is checked by the claim checker before the packet is saved. |

All agents share **one Relate graph**. They write through transactions, so two agents touching the same control can't overwrite each other.

## Rules the agents must follow (enforced by Crosswalk, not by trust)

1. **Receipts or it didn't happen.** Every factual claim carries path ids. The **claim checker** re-runs each path. Claims that fail are removed or flagged before the user sees them.
2. **Propose, don't write.** Agents can only create `:Proposal` nodes. Only a human `approve` turns a proposal into a real `SATISFIES` edge or a status change.
3. **Verified before review.** Each proposal is checked automatically:
   - Is the target real?
   - Is the control already mapped?
   - Does the mapping agree with the NIST crosswalk?
   - Was it rejected before?
4. **Memory of decisions.** Approvals and rejections, with reasons, are stored as `:Decision` nodes. Agents must read them before proposing.

## Who it's for

| User | What they get |
|---|---|
| **Security or compliance lead** at a 20 to 200 person SaaS company (primary) | A chat assistant that gives correct, cited answers, plus coverage, gaps, reuse and expiry risk |
| **Control owners** (engineers, IT, HR) | Drafted, specific evidence requests instead of vague tickets |
| **Auditors** | Verifiable chains from requirement to control to evidence |
| **Coding-agent users** (Claude Code, Cursor) | `relate skill install` plus MCP, so compliance questions work inside the tools they already use |

## Industry

**Governance, risk and compliance (GRC) within cybersecurity.** Multi-framework compliance is now the norm. A 2026 roundup notes that most organisations maintain more than one framework at once ([Mitratech](https://mitratech.com/resource-hub/blog/top-11-grc-tools-for-security-compliance-and-it-leaders-in-2026/)).

## Impact on users (Usefulness, 20 points)

1. **Correct answers, not confident guesses.** We measure the agent with the graph against the agent with spreadsheets (05).
2. **Less duplicate work.** Measured as the evidence reuse ratio across frameworks.
3. **Faster mapping.** The mapper agent's suggestions are scored against NIST's official crosswalk.
4. **No audit surprises.** Expiring evidence is flagged 30 days ahead, with requests already drafted.
5. **Rejections stick.** The agent learns from human "no"s within the same graph.

## Honest positioning: alternatives exist

| Alternative | What it does | Where Crosswalk differs |
|---|---|---|
| Spreadsheets | The default for small teams | No paths, no automation, no agent |
| Paid GRC SaaS: Vanta, Drata, Hyperproof ([Vanta](https://www.vanta.com/collection/grc/multi-framework-cross-mapping), [Hyperproof](https://hyperproof.io/resource/crosswalks-between-compliance-frameworks/)) | Crosswalks, evidence collection and integrations | Free and open, local, the graph is inspectable, the agent's accuracy is measured publicly, and it plugs into any MCP agent |
| Free crosswalk tools such as [crosswalker](https://cybersader.github.io/crosswalker/getting-started/grc-teams/) | Framework-to-framework mapping | Crosswalk adds the company layer (controls, evidence, owners, audits) plus agents with verified answers |
| Asking ChatGPT or Claude directly | Quick answers | Can't see your evidence dates or past decisions, and can't prove claims |

**Crosswalk doesn't replace a GRC platform.** It shows an open, agent-native core that such tools, or a small team on its own, could use.

**"Why not Vanta?" in one line** (this exact sentence goes near the top of the README):

> *Crosswalk is free, runs locally, and lets you inspect every link in the graph. It works with any MCP agent, it is built on NIST's official crosswalk, and its accuracy is measured and published.*

## What connects to what (for Devpost)

> Frameworks contain requirements, and NIST's official crosswalk links requirements across frameworks. A company's controls satisfy requirements, evidence proves controls, controls apply to systems, people own controls, and audits scope frameworks. On top of that, agents create proposals and claims that cite paths, and humans record decisions that agents must respect. One graph holds both the compliance facts and the agent's working memory.

## Data (public and fictional only)

| Input | Source | Licence | Status |
|---|---|---|---|
| NIST SP 800-53 Rev 5 | NIST OSCAL content (JSON) | US government work | **Verify on day 1** |
| NIST CSF 2.0 | NIST reference data | US government work | **Verify on day 1** |
| NIST SP 800-171 Rev 3 | NIST | US government work | **Verify on day 1** |
| Official crosswalks (CSF 2.0 ↔ 800-53, 800-171 ↔ 800-53) | NIST CPRT / OLIR | US government work | **Verify on day 1**. This is the ground truth. |
| **Real open-source policy templates**: the company's policies and control wording | Candidates: **JupiterOne `security-policy-templates`** and **StrongDM `comply`** (24 SOC 2-style policies in Markdown) ([StrongDM](https://www.strongdm.com/blog/soc-2-policy-templates), [JupiterOne mirror listing](https://relatedrepos.com/gh/JupiterOne/security-policy-templates)) | **Unconfirmed. Check each repo's LICENSE on day 1.** If it is a share-alike licence (e.g. CC BY-SA), keep the files in `inputs/templates/` with their own licence and attribution, separate from our Apache-2.0 code. | Pick one set. Its policies become `:Policy` nodes, and its control statements become our `:Control` text. |
| Company pack, "Harbor & Pine (fictional)" | We write it **on top of the real templates**: systems, people, owners, evidence items with dates, 3 audits | Ours, Apache-2.0 | Includes **planted scenarios** with known answers |

**Why this matters:** controls and policies use wording written for real companies, so mapping them to NIST is a realistic test, not one we made easy for ourselves. Only the company itself (its people, systems and evidence dates) is invented.

**Not used:** CISO Assistant's libraries. They appear to be AGPL, which doesn't fit our Apache-2.0 repo, and some frameworks there need a manual download because of their licence ([README](https://github.com/intuitem/ciso-assistant-community/blob/main/README.md)).

ISO 27001 and SOC 2 texts are excluded because they are copyrighted. The README notes that they would plug into the same model.

## AI dependency (stated clearly)

- **The core runs without any AI:** build, coverage, adopt, blast radius, reuse, hybrid suggestions, approvals, the browser explorer and the scorecard. Judges can run all of it with no API key.
- **The agents run in any MCP client.** The demo uses Claude Code. Anyone without a key can read the published agent transcripts. Compliance data may be sensitive, so the README notes that a local model can be used through the same MCP server.

## Out of scope

Crosswalk is not legal or audit advice. It has no real company data and no SaaS integrations (Jira, AWS and so on). Agents never send messages or change records on their own.
