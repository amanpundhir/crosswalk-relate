# 04 · Architecture, inputs, graph model, agents, flows and UI

## Big picture

```
 INPUTS                          BUILD (Python + relate-db)                 STORE                         SURFACES
 ──────                          ──────────────────────────                 ─────                         ────────
 NIST 800-53 (OSCAL JSON) ─┐                                                                              ┌─ CLI: crosswalk <cmd>            (people)
 NIST 800-171              ├─► parse ─► normalise ─► embed ─► load ───► data/crosswalk/ ◄───────────────┼─ crosswalk-mcp (narrow tools)   (agents: propose, cite, check)
 NIST CSF 2.0              │                         (local     (txn     (directory store,  ◄─ read-only ─┼─ relate serve --mcp --read-only (agents: get_schema, read_cypher)
 NIST official crosswalk ──┤                          384-d)    batches)  JSON codec,                     ├─ Browser: WASM explorer          (judges, what-if)
 Company pack (YAML) ──────┘                                              committed)                      └─ Eval: crosswalk scorecard       (KPIs)
                                                                               │
                                                                               └─► export web/graph.cypher (browser)

 AGENT LOOP (Claude Code or any MCP client)
 question ─► read graph (MCP) ─► draft answer with path ids ─► CLAIM CHECKER re-runs paths ─► verified answer
                                └► propose change ─► PROPOSAL VERIFIER ─► human approve/reject ─► Decision stored ─► agents read decisions next time
```

## Inputs

| Input | Format | Size | Notes |
|---|---|---|---|
| Framework catalogs | OSCAL JSON, CSV/XLSX | ~1,200 to 1,500 requirements | ids, titles, text, family hierarchy |
| Official crosswalk | CSV/XLSX from NIST | ~1,000+ rows | `EQUIVALENT_TO` edges and **ground truth** |
| **Real policy templates** | Markdown from one open-source set (JupiterOne `security-policy-templates` or StrongDM `comply`; licence checked on day 1) in `inputs/templates/` | ~20 to 25 policies | Become `:Policy` nodes. Their control statements become the text of our `:Control` nodes. |
| Company pack ("Harbor & Pine (fictional)") | YAML in `inputs/company/`, which references the template controls by id | ~60 controls (wording from the templates), 120 evidence items, 25 systems, 15 people, 3 audits | Only people, systems, owners and dates are invented. Includes planted scenarios (05). |
| Questions | Natural language, sent to the agent | — | 20 golden questions plus free chat |
| Human decisions | `crosswalk review` (approve or reject, with a reason) | — | Stored as `:Decision` |

## Graph model

### Compliance facts

```
(:Framework {id, name, version}) ◄─PART_OF─ (:Family) ◄─PART_OF─ (:Requirement {id, framework, title, text, embedding[384]})
(:Requirement) ─[:EQUIVALENT_TO {source:'NIST', relationship}]─ (:Requirement)
(:Control {id, title, description, embedding[384], status}) ─[:SATISFIES {approved_by, approved_at}]─► (:Requirement)
(:Evidence {id, kind, collected_at, expires_at, location}) ─[:PROVES]─► (:Control)
(:Control) ─[:APPLIES_TO]─► (:System {name, criticality})
(:Person {name, team, role}) ─[:OWNS]─► (:Control | :Evidence)
(:Policy) ─[:MANDATES]─► (:Control)
(:Audit {id, name, date}) ─[:SCOPES]─► (:Framework)   ─[:REQUESTS]─► (:Evidence)
```

### Agent working memory and audit trail (in the same graph)

```
(:Agent {name, role, model})
(:Proposal {id, kind: map|status|evidence_request, verified, verify_reason, score, rationale, created_at})
    ─[:BY]─► (:Agent)   ─[:ABOUT]─► (:Control)   ─[:TARGET]─► (:Requirement | :Evidence | :Person)
(:Decision {outcome: approved|rejected, reason, by, at}) ─[:ON]─► (:Proposal)
(:Claim {text, verified, checked_at}) ─[:CITES]─► (:Path {id, node_ids, rel_types})  ─[:IN_ANSWER]─► (:Answer {question, at, agent})
(:Change {at, actor, action}) ─[:CHANGED]─► (any node)
```

**Why keep agent memory in the same graph:** an agent can ask in one query, "has a human already rejected mapping CTRL-061 → AC-17, and why?". The answer sits right next to the facts. This is the "connected context makes the agent reliable" point in its purest form.

### Indexes

- A vector index on `Requirement.embedding` `WITH [framework]`.
- Full-text indexes on requirement text and on control text.

## Storage mode: directory store with the JSON codec

For the README's "Why this mode":

1. **Readers next to a writer.** The Relate MCP server runs `--read-only=live` (it follows commits) while `crosswalk-mcp` and the CLI write proposals and decisions. A `.rl` file would refuse read-only opens while a writer holds it. **This is the main reason. Several agents are reading and writing at the same time.**
2. **Inspectable on GitHub.** `graph.json` can be read with no install.
3. **Diffable, with a helper.** Day-1 testing showed `graph.json` is one long line and is rewritten only at a checkpoint. So:
   - `crosswalk build` and `crosswalk review` always close cleanly, which forces a checkpoint before anything is committed.
   - The build also writes a **sorted, pretty-printed export** (`exports/graph.pretty.json`, one node or relationship per line). That export is what makes git diffs readable.
   - A CI check fails if the committed store's `wal/` holds uncheckpointed commits.
4. **Small.** ~3k nodes, ~10k relationships and embeddings come to a few MB.
5. `relate clone` makes a `.rl` copy on demand.

## Agent tool surface (two MCP servers)

| Server | Tools | Access |
|---|---|---|
| **Relate's own MCP** (`relate serve --mcp stdio --database ./data/crosswalk --read-only=live`) | `get_schema`, `read_cypher` | Read-only, for free exploration |
| **crosswalk-mcp** (ours, small, Python) | `coverage(framework)`, `adopt(framework)`, `blast(days)`, `suggest(control, framework, k)`, `explain(requirement)`: each returns results **with path ids** | Read |
| | `propose_mapping(control, requirement, rationale)`, `propose_evidence_request(evidence, person, draft)`, `propose_status(control, status, rationale)` | Write **proposals only** |
| | `decisions(about)`: past approvals and rejections | Read |
| | `check_claims(answer)`: re-runs every cited path, returns verified or failed per claim | Read |

Agents **cannot** call Relate's `write_cypher`; that server runs read-only. All writes go through the narrow `propose_*` tools, so an agent can't corrupt facts.

Agent prompts live in `agents/`, one prompt or skill file per role.

### One-step agent setup: `crosswalk agent setup`

A judge runs one command instead of editing config files by hand. It:

1. Checks that the `relate` CLI is installed (and prints the install command if not).
2. Runs `relate skill install --agent claude-code`, so Claude Code knows how to use Relate.
3. Registers **both** MCP servers for the chosen client: Relate's read-only server and `crosswalk-mcp`, with the correct absolute paths to `data/crosswalk/`.
4. Copies the four agent role prompts into the client's skills or commands folder.
5. Runs a self-test: it calls `get_schema` and `coverage("800-171")` through MCP and prints ✔ or a fix-it message.

Options: `--agent claude-code` (default) or `cursor`, plus `--dry-run` to print what would change, and `--undo` to remove everything it added. Some files it touches live outside the repo, such as the client's MCP config, so it always shows the changes first and asks before writing them.

### The claim checker (how "receipts" work)

1. The tools return path ids. A path id is a stable hash of the node and relationship ids along a path, for example requirement → control → evidence.
2. The agent must attach the path ids to each claim in its answer.
3. `check_claims` confirms that each path still exists **and** is still valid: the evidence hasn't expired and the mapping is approved, not only proposed.
4. Claims that fail are dropped or marked ⚠ with the reason. The final answer shows "12/12 claims verified".

### The proposal verifier (runs automatically on every proposal)

| Check | Example failure |
|---|---|
| Target exists, and the framework matches the request | "Requirement 03.99.01 does not exist" |
| Not a duplicate | "Already satisfied (approved 2026-11-30)" |
| **Not previously rejected** | "Rejected by Maya on Dec 2: 'AC-17 is remote access, this control is local'" |
| Crosswalk consistency | "Agrees with NIST: AC-2 ↔ 03.01.01" (raises confidence) or "No NIST link" (flag for careful review) |
| Evidence requests: owner exists and evidence really expires soon | "EV-012 is valid until 2027-06, so no request is needed" |

## The six core questions (used by the CLI, the tools and the browser)

| # | Question | Traversal in words |
|---|---|---|
| Q1 | Coverage of framework F, with gaps | Framework → requirements, minus those reached by an approved `SATISFIES` from a control with valid `PROVES` |
| Q2 | Adopt a new framework | Control → `SATISFIES` → requirement → `EQUIVALENT_TO` (1 hop; see spec v1.1) → requirement in F |
| Q3 | Blast radius of expiring evidence | Evidence (expiring) → controls left with no other valid evidence → requirements → frameworks → audits |
| Q4 | Evidence reuse | Evidence → controls → requirements, counted by distinct framework |
| Q5 | Mapping candidates | Hybrid search (vector + full text with WRRF) on control text, filtered by framework, re-ranked by graph context: crosswalk neighbours, sibling requirements, past decisions |
| Q6 | Owner risk | Person → `OWNS` → controls with a single owner → requirements and audits affected |

Plus **Explain**: requirement ← control ← evidence, with dates.

## User flows

### Flow A: Maya asks the audit-prep agent (primary)

1. Maya, in Claude Code: *"Are we ready for the Jan 15 800-171 audit? What should I do this week?"*
2. The agent calls `coverage("800-171")`, `adopt("800-171")` and `blast(30)`, then `decisions()`.
3. It drafts an answer: "78% covered. 21 of 34 gaps are already met through 800-53 mappings. EV-044 expires Dec 30 and breaks 9 requirements. Top 3 actions this week…". Each claim carries its path ids.
4. `check_claims` runs: 11 of 12 verified. One claim cited a mapping that is still **proposed**, not approved, so it is marked ⚠ "pending approval".
5. Maya sees the verified answer with ✔ and ⚠ badges and can open any path in the explorer.

### Flow A2: the live catch (the "wow" moment, built as a repeatable scenario)

This is the centre of the demo. It is built as a planted scenario so it happens the same way every time, not by luck:

1. **The setup (planted):** EV-044, the only evidence for CTRL-007 "MFA on admin accounts", expired yesterday. The company's old spreadsheet export still says "MFA: ✔ compliant". A mapping CTRL-012 → 03.05.03 is only *proposed*, not approved.
2. Maya asks: *"Is MFA covered for the 800-171 audit?"*
3. The agent answers confidently: **"Yes. 03.05.03 is fully covered by CTRL-007 and CTRL-012."** This is what any assistant would say from the spreadsheet.
4. **The graph catches it live.** The claim checker re-runs both cited paths and shows the result on screen in under a second:
   - ✖ *CTRL-007 → EV-044: evidence expired 2026-12-01*
   - ⚠ *CTRL-012 → 03.05.03: mapping is proposed, not approved*
5. Crosswalk then prints the corrected answer: **"Not covered. Renew EV-044 (owner: Dana, request drafted) and review the CTRL-012 proposal."**
6. In the browser, the Agent log tab shows the failed claim in red, and clicking it highlights the broken path in the graph.

`crosswalk demo live-catch` replays this from a clean copy of the store, so judges can see it without an AI key. It replays the recorded agent answer, while the claim check runs live. It is also a pytest.

### Flow B: the mapper agent on a new control (human in the loop)

1. A new control, CTRL-061 "Quarterly review of VPN accounts", is added to the company pack.
2. The mapper agent calls `suggest("CTRL-061", "800-53", 10)` to get hybrid candidates with path context.
3. It reads `decisions(about: CTRL-061 neighbours)` and finds that Maya rejected a similar mapping to AC-17 last week, with her reason.
4. It proposes 3 mappings with rationales, and skips the one that matches the earlier rejection.
5. The verifier marks them: 2 agree with the NIST crosswalk, 1 has no NIST link.
6. `crosswalk review`: Maya approves 2 and rejects 1 with a reason. Each decision is **one transaction** that moves the proposal to `SATISFIES` or `:Decision{rejected}`, writes a `:Change` and returns a bookmark.
7. Coverage updates. Next time, the agent sees the new rejection.

### Flow C: two agents at the same time (safe shared state)

**Measured behaviour (Relate 1.2.0, Windows; see `src/crosswalk/demo_concurrency.py`):**

- **Embedded mode:** a directory store has **one writer lease**, even across threads. A second writer is refused immediately with `storage locked` (not retryable), and our `open_writer` waits until the lease is free. Nothing is lost, but nothing runs in parallel either.
- **Served mode** (`relate serve --http`): transactions overlap and commit optimistically. The later commit fails with `write-write conflict` (`retryable=True`), our code retries, and both writes land. **The two-agent demo uses served mode**, because that's where Relate's transaction safety shows.

In production use, all agent writes go through `crosswalk-mcp`, one process that holds the writer, so agents never fight over the lease.

The evidence agent marks CTRL-007 "at risk" because its only evidence expires. At the same moment, the mapper agent proposes a mapping for CTRL-007. Both writes are transactions. If they conflict, Relate reports a retryable conflict, our tool retries, and both changes land with no silent overwrite. The demo shows the conflict and the retry in the log.

### Flow C2: the auditor-packet agent

1. Maya asks: *"Prepare the packet for the Jan 15 800-171 audit."*
2. The agent walks every requirement in the audit's scope using `explain()`. For each one it collects the control, the evidence with dates and the owner.
3. Every line is passed through `check_claims` before it is written. Lines that fail are kept but marked ⚠ with the reason, never hidden.
4. The output is `out/packets/800-171-2027-01-15.md`: a summary table, one section per requirement, and a list of open items. It is also saved as an `:Answer` node so the browser can show it.

### Flow D: a judge explores in the browser (no install, no AI)

Open the GitHub Pages link. It has these tabs:

- **Coverage**
- **Adopt**
- **Blast**
- **Graph**
- **Agent log**: proposals, decisions and claim checks, read from the graph
- **Scorecard**

What-if: expire an evidence item or remove a person, and coverage drops live. These changes are in memory only.

### Flow E: no AI at all

Every core question works from the CLI: `crosswalk coverage`, `adopt`, `blast`, `reuse`, `suggest`, `owners`, `explain` and `review`. This is the path for judges without an API key, and for teams that can't send compliance data to an AI service.

## UI

| Surface | Purpose | Notes |
|---|---|---|
| **Agent chat** (Claude Code or any MCP client) | Main experience for the agent story | Answers show ✔/⚠ per claim with path ids |
| **CLI** (Python + Rich) | Direct work, review queue, scorecard | `--json` on every command |
| **Browser explorer** (static, Relate WASM, Cytoscape.js or Sigma.js) | Judges, demo, what-if, agent log | GitHub Pages, no backend |
| **Scorecard** (`eval/scorecard.md` + browser tab) | KPIs | Regenerated in CI |

### Browser screen sketch

```
┌ Crosswalk ── "An audit-prep agent that answers with receipts." ───────────────── [Reset what-if] ┐
│ Framework: [800-171 ▾]   Audit: [800-171 assessment, Jan 15 ▾]                                    │
├──────────────┬───────────────────────────────────────────────────────────────────────────────────┤
│ Coverage     │  800-171 ███████████████░░░░ 78%   gaps 34   adopt-able 21   expiring before audit 3│
│ Adopt        │  ┌ Agent log ─────────────────────────────────────────────────────────────────────┐ │
│ Blast radius │  │ mapper   PROPOSED CTRL-061 → AC-2      ✔ verified (NIST agrees)  → APPROVED Maya │ │
│ Graph        │  │ mapper   PROPOSED CTRL-061 → AC-17     ✖ skipped: rejected Dec 2 ("local only")  │ │
│ Agent log    │  │ prep     Answer "ready for 800-171?"   11/12 claims ✔   1 ⚠ pending approval     │ │
│ Scorecard    │  └─────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────────────────────────┘
```

The first 10 seconds must show what it is, who it's for, and two obvious buttons: **"Show audit gaps"** and **"See the agent's receipts"**.

## Repo layout (planned)

```
README.md               official template + requirements map + scorecard + responsible AI
LICENSE                 Apache-2.0
inputs/nist/            raw NIST files + SOURCES.md (URLs, dates, licences)
inputs/templates/       real open-source policy templates (kept under their own licence + attribution)
inputs/company/         fictional company pack (people, systems, evidence, audits) + planted-scenario notes
data/crosswalk/         ★ the persistent Relate store (directory, JSON codec)
exports/                graph.pretty.json (diffable, generated) + graph.cypher for the browser
src/crosswalk/          build, queries, claim checker, proposal verifier, review, agent setup, demo replay, CLI, eval
src/crosswalk_mcp/      the narrow MCP server for agents
agents/                 role prompts/skills: audit-prep, mapper, evidence, (auditor-packet) + MCP config examples
queries/                one .cypher file per core question (cookbook)
web/                    WASM explorer + graph.cypher export
eval/                   ground truth, golden questions, agent-runs/ transcripts, scorecard.md/.json
docs/                   schema.md, queries.md, plan/ (these files)
.github/workflows/      build, tests, scorecard, Pages deploy (no secrets needed)
```

## Third-party tools (to disclose)

- relate-db (Python) and @relate/relate-wasm
- one open-source policy template set (JupiterOne or StrongDM, used under its own licence with attribution)
- the MCP Python SDK, for crosswalk-mcp
- a small local sentence-embedding model (384-d; licence and size to be checked)
- Typer/Click and Rich
- a JS graph renderer
- pytest, GitHub Actions and Pages

AI: Claude Code helps write code and docs, and Claude is the MCP agent in the demo and evaluation.
