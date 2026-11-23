# Query cookbook

Every Crosswalk question is a `.cypher` file in [`queries/`](../queries/). The CLI, the MCP server and the browser explorer all run the same text (`web/queries/` holds byte-for-byte copies of the nine the explorer uses; `python -m crosswalk.export_web` refreshes them). Excerpts below are trimmed; the files have the full comments and the path lists.

Two rules every query follows:

* **Dates**: the demo date is read from `(:Meta).as_of` (2026-12-02) and passed in as `$as_of`. Nothing reads the system clock.
* **Valid evidence** means `expires_at > $as_of`. **Covered** means an adopted control with an approved `SATISFIES` to the requirement, proved by valid evidence.

Rows that assert something also return `nodes` and `rels` lists. `src/crosswalk/paths.py` hashes them into the path ids that the claim checker re-runs (see [schema.md](schema.md), "Path ids").

## Run any query by hand

Read-only, next to a writer (the store is committed, so no build is needed):

```bash
# macOS / Linux (Git Bash on Windows also works)
relate query -d data/crosswalk --read-only=live --mode jsonl \
  --param 'framework="800-171"' --param 'as_of="2026-12-02"' < queries/q1_coverage.cypher
```

```powershell
# Windows PowerShell 5.1: go through cmd so the file reaches stdin without a byte-order mark
cmd /c '.venv\Scripts\relate.exe query -d data/crosswalk --read-only=live --mode jsonl --param framework=\"800-171\" --param as_of=\"2026-12-02\" < queries\q1_coverage.cypher'
```

Output starts with `{"as_of":"2026-12-02","covered":15,"framework":"800-171","gaps":59,"inherited":23,...`. Parameter values are JSON, so strings need their quotes. A one-line statement needs no file: `relate -d data/crosswalk --read-only=live --mode jsonl "MATCH (c:Control {adopted:true}) RETURN count(c) AS adopted"` prints `{"adopted":61}`.

## Index

| # | Question | File | CLI | MCP tool |
|---|---|---|---|---|
| Q1 | How much of framework F is covered, and what are the gaps? | `q1_coverage.cypher`, `q1_paths.cypher` | `crosswalk coverage -f 800-171` | `coverage` |
| Q2 | If we adopt framework F, what do we already meet through the NIST crosswalk? | `q2_adopt.cypher` | `crosswalk adopt 800-171` | `adopt` |
| Q3 | What loses coverage if expiring evidence is not renewed? | `q3_blast.cypher` | `crosswalk blast --audit AUD-171` | `blast` |
| Q4 | Which evidence item earns the most compliance credit across frameworks? | `q4_reuse.cypher` | `crosswalk reuse` | `reuse` |
| Q5 | Which requirements does a control probably satisfy? | `q5_*.cypher` (7 files) | `crosswalk suggest CTRL-AOTP-4` | `suggest` |
| Q6 | What if a person leaves? Which controls have one owner or none? | `q6_owner_risk.cypher` | `crosswalk owners` | `owners` |
| Explain | Why is this requirement covered, inherited or a gap? | `explain.cypher` | `crosswalk explain 800-171:03.05.03` | `explain` |
| Stale | Where does the old spreadsheet say Compliant but the graph disagrees? | `stale_tracker.cypher` | `crosswalk stale` | `stale` |
| Evidence | Which evidence has expired or is about to? | `evidence_list.cypher` | `crosswalk evidence --audit AUD-171 --status lapsed` | `evidence` |
| Check | Is the path an agent cited still real and valid? | `check_path.cypher`, `check_absence.cypher`, `all_paths.cypher`, `proposed_paths.cypher` | `crosswalk check answer.json` | `check_claims` |
| Decisions | What did a human already approve or reject, and why? | in `src/crosswalk/review.py` | `crosswalk decisions` | `decisions` |

## Q1 Coverage and gaps

**File:** `queries/q1_coverage.cypher` (totals and per-requirement status), `queries/q1_paths.cypher` (the receipts).
**Computes:** for every requirement of the framework, whether it is `covered` (an approved `SATISFIES` from an adopted control that has valid evidence), `inherited` (not covered, but one `EQUIVALENT_TO` hop away is a covered requirement; only for 800-171 and CSF) or a `gap`. Returns totals plus the list.

```cypher
MATCH (r:Requirement {framework: $framework})-[:PART_OF]->(f:Family)
OPTIONAL MATCH (r)<-[:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
WITH r, f, collect(DISTINCT c.id) AS controls, collect(DISTINCT e.id) AS evidence
OPTIONAL MATCH (r)-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c2:Control {adopted: true})<-[:PROVES]-(e2:Evidence)
WHERE $framework <> '800-53' AND size(controls) = 0 AND e2.expires_at > date($as_of)
...
```

```
crosswalk coverage -f 800-171            # family table; last line: covered 15/97 (15%), inherited 23, gaps 59
crosswalk coverage -f 800-171 --detail --status gap
crosswalk coverage --audit AUD-53        # restrict to an audit's scope (800-53 MODERATE baseline)
```

## Q2 Adopt a framework

**File:** `queries/q2_adopt.cypher`.
**Computes:** requirements of the new framework that have no direct coverage but sit one `EQUIVALENT_TO` hop from a requirement that is covered. One row per proving path: `Requirement -EQUIVALENT_TO- Requirement <-SATISFIES- Control <-PROVES- Evidence`. One hop only; two hops through CSF informative references proved too loose.

```cypher
MATCH (r:Requirement {framework: $framework})
WHERE $framework <> '800-53'
  AND NOT EXISTS { MATCH (r)<-[:SATISFIES]-(:Control {adopted: true})<-[:PROVES]-(d:Evidence)
                   WHERE d.expires_at > date($as_of) }
MATCH (r)-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
RETURN DISTINCT r.id AS requirement, n.id AS neighbour, c.id AS control, e.id AS evidence, ...
```

```
crosswalk adopt 800-171     # 23 of 97 (24%) already met through the crosswalk
crosswalk adopt CSF         # 81 of 106 (76%)
```

## Q3 Blast radius

**File:** `queries/q3_blast.cypher`.
**Computes:** take the evidence that is valid today but expires inside the window (`--days N`, `--until DATE`, or before an audit with `--audit`). A requirement is **broken** if it is covered directly now and no covering control keeps valid evidence past the cutoff. An evidence item that expired but has a valid replacement for the same control is not flagged. Each broken requirement says whether it is still met through the crosswalk. Audits are affected when they request an expiring item or their framework has a broken requirement.
The result is a tagged union (`kind` is `expiring`, `control_left`, `broken` or `audit`) built with `UNION ALL`.

```cypher
MATCH (r:Requirement)<-[:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
WITH r, collect(DISTINCT c.id) AS controls_lost, collect({c: c.id, e: e.id}) AS lost_pairs,
     count(CASE WHEN e.expires_at > date($until) THEN 1 END) AS survivors
WHERE survivors = 0
OPTIONAL MATCH (r)-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c2:Control {adopted: true})<-[:PROVES]-(e2:Evidence)
WHERE r.framework <> '800-53' AND e2.expires_at > date($until)
...
RETURN 'broken' AS kind, {requirement: r.id, still_inherited: size(inh) > 0, ...} AS data
```

```
crosswalk blast --days 30         # 800-171: 6 lose direct coverage (2 fully broken, 4 still met via another framework)
crosswalk blast --audit AUD-171   # 800-171: 9 lose direct coverage (4 fully broken, 5 still met); 800-53: 5, all fully broken
crosswalk blast --until 2027-01-15
```

## Q4 Evidence reuse

**File:** `queries/q4_reuse.cypher`.
**Computes:** for each still-valid evidence item, the adopted controls it proves, the distinct requirements those controls satisfy (direct), the requirements one crosswalk hop further out, and the frameworks reached. Ranked by direct requirements, then frameworks reached, then total reach, then id. This is the "collect once, answer several audits" number.

```cypher
MATCH (e:Evidence) WHERE e.expires_at > date($as_of)
OPTIONAL MATCH (e)-[:PROVES]->(c1:Control {adopted: true})-[:SATISFIES]->(d:Requirement)
...
OPTIONAL MATCH (e)-[:PROVES]->(c2:Control {adopted: true})-[:SATISFIES]->(d2:Requirement)-[:EQUIVALENT_TO]-(h:Requirement)
...
ORDER BY direct_count DESC, framework_count DESC, reach_count DESC, e.id ASC
```

```
crosswalk reuse --top 5
```

## Q5 Mapping candidates (hybrid search plus graph context)

**Files:** `q5_control.cypher` (the control's text and embedding), `q5_suggest_vector.cypher`, `q5_suggest_fulltext.cypher`, `q5_suggest_hybrid.cypher`, `q5_candidate_family.cypher` and `q5_graph_signals.cypher` (re-rank).
**Computes:** candidate requirements for a control, from one framework (default 800-53). Four methods: `fulltext`, `vector`, `hybrid` and `hybrid+graph` (default).

* **Vector**: Relate `SEARCH ... VECTOR INDEX` over `Requirement.embedding`, pre-filtered to one framework by the index's `WITH [framework]` clause.
* **Full text**: `SEARCH ... FULLTEXT INDEX` (BM25). A full-text `SEARCH` needs a `LIMIT` and cannot filter by framework inside the index, so the framework filter is applied after.
* **Hybrid**: the two ranked lists are fused by hand with weighted reciprocal-rank fusion, `score = 0.7 / (60 + rank_vector) + 0.3 / (60 + rank_fulltext)`, in one `CALL { ... UNION ALL ... }`.
* **Graph re-rank**: the top 30 hybrid candidates get a bonus when their family already holds an approved mapping from another control of the same policy (+0.15) or the control's existing mapping is one crosswalk hop away (+0.25), and a penalty when a human rejected that exact mapping (-1.0). The signals come from `q5_graph_signals.cypher`.

```cypher
CALL () {
  MATCH (r:Requirement)
    SEARCH r IN (VECTOR INDEX requirement_embedding FOR $v WHERE r.framework = $framework LIMIT $pool)
    SCORE AS s
  ...
  UNION ALL
  MATCH (r:Requirement)
    SEARCH r IN (FULLTEXT INDEX requirement_text_ft FOR $q LIMIT $ft_pool)
    SCORE AS s
  WHERE r.framework = $framework
  ...
}
WITH id,
     sum(CASE src WHEN 'vector' THEN $w_vec / ($rrf_c + rank) ELSE 0.0 END) AS vector_part,
     sum(CASE src WHEN 'fulltext' THEN $w_ft / ($rrf_c + rank) ELSE 0.0 END) AS fulltext_part, ...
```

```
crosswalk suggest CTRL-AOTP-4 --k 5
crosswalk suggest CTRL-AOTP-4 --method vector      # fulltext | vector | hybrid | hybrid+graph
crosswalk propose-map CTRL-AOTP-4 800-53:AC-2 -r "why"   # suggestions are not mappings; this writes a verified Proposal
```

Measured quality of these methods is in the README ("Mapping quality") and in `eval/mapping_scores.md`.

## Q6 Owner risk

**File:** `queries/q6_owner_risk.cypher`.
**Computes:** a tagged union. `person`: controls only that person owns, the requirements and systems behind them, and which systems are high criticality. `dependent`: requirements that are covered today where every covering control is solely owned by the same person (if she leaves, nobody owns the coverage), with the audits that scope the framework. `unowned`: adopted controls nobody owns.

```cypher
MATCH (p:Person)
OPTIONAL MATCH (p)-[:OWNS]->(c:Control {adopted: true})
WHERE size([(o:Person)-[:OWNS]->(c) | o]) = 1
...
UNION ALL
MATCH (c:Control {adopted: true})
WHERE NOT (c)<-[:OWNS]-(:Person)
RETURN 'unowned' AS kind, {control: c.id, title: c.title, status: c.status} AS data
```

```
crosswalk owners
```

## Explain

**File:** `queries/explain.cypher`.
**Computes:** for one requirement: a summary, every `Requirement <- Control <- Evidence` path with owners, approval and dates (`valid` true or false, expired paths included so the answer can say why it is not covered), inherited paths through a covered neighbour (non-800-53 only), and proposed mappings aimed at it with any human decision.

```cypher
MATCH (r:Requirement {id: $requirement})<-[s:SATISFIES]-(c:Control {adopted: true})
OPTIONAL MATCH (c)<-[:PROVES]-(e:Evidence)
RETURN 'path' AS kind,
       {control: c.id, evidence: e.id, expires_at: toString(e.expires_at),
        valid: e IS NOT NULL AND s.approved_by IS NOT NULL AND e.expires_at > date($as_of), ...} AS data
```

```
crosswalk explain 800-171:03.05.03        # or just 03.05.03; --md prints Markdown, --json everything
```

For `800-171:03.05.03` it prints `as of 2026-12-02: gap`, the expired path through EV-044, and `proposed, not approved: PR-005 CTRL-PWP-4 (pending)`. This is the live catch.

## Stale tracker rows

**File:** `queries/stale_tracker.cypher`.
**Computes:** one row per legacy-spreadsheet row (`TrackerRow`) next to what the graph knows about the same control: owners, every evidence item with `valid`, approved mappings and proposals. `crosswalk stale` then picks the "Compliant" rows the graph contradicts (no valid evidence, no owner, ...).

```cypher
MATCH (t:TrackerRow)-[:ABOUT]->(c:Control)
RETURN t.id AS tracker, c.id AS control, t.status_text AS status_text,
       [(o:Person)-[:OWNS]->(c) | o.id] AS owners,
       [(e:Evidence)-[:PROVES]->(c) | {evidence: e.id, expires_at: toString(e.expires_at),
                                        valid: e.expires_at > date($as_of)}] AS evidence, ...
```

```
crosswalk stale      # 5 of 46 'Compliant' rows are contradicted; --all also lists the ones the graph agrees with
```

## Evidence list

**File:** `queries/evidence_list.cypher`.
**Computes:** every evidence item with its status at the demo date: `expired` (`expires_at <= as_of`), `expiring` (valid today, gone by the cutoff) or `valid`, plus owners, the controls it proves and the audits that request it. Filtering by audit and status happens in the CLI.

```cypher
MATCH (e:Evidence)
RETURN e.id AS evidence,
       CASE WHEN e.expires_at <= date($as_of) THEN 'expired'
            WHEN e.expires_at <= date($until) THEN 'expiring'
            ELSE 'valid' END AS status, ...
```

```
crosswalk evidence --audit AUD-171 --status lapsed     # expired + expiring; cutoff is the audit date
```

## Check a claim (the receipts)

**Files:** `check_path.cypher` re-runs one cited path and says whether it exists and is valid; `check_absence.cypher` checks "nothing is there" receipts; `all_paths.cypher` enumerates every path shape the commands can cite, so a fresh process can resolve an id; `proposed_paths.cypher` turns pending proposals into citable paths so an agent can say "proposed, not approved".
**Computes (`check_path`):** every hop must exist with the right label, id, type and direction. It is valid when every `SATISFIES` hop is approved, every control on it is adopted, every evidence on it has `expires_at > $as_of`, and every proposal on it is approved. The result is `exists`, `valid` and human-readable `problems`.

```cypher
UNWIND range(0, size($rels) - 1) AS i
WITH i, $nodes[i] AS a_ref, $nodes[i + 1] AS b_ref, $rels[i] AS token
...
OPTIONAL MATCH (a)-[r]-(b)
WHERE a.id = a_id AND a_label IN labels(a) AND b.id = b_id AND b_label IN labels(b)
  AND type(r) = rel_type
  AND (rel_type = 'EQUIVALENT_TO' OR (NOT reversed AND startNode(r) = a) OR (reversed AND endNode(r) = a))
```

```
crosswalk check eval/agent-runs/live-catch-recorded.json    # prints ✖ / ⚠ per claim; exit code 1 if any claim is not ✔
crosswalk demo live-catch                                   # the same case, replayed on a temp copy of the store
```

## Decisions and the review queue

Not a `.cypher` file; the queries are in `src/crosswalk/review.py`. `crosswalk decisions` lists `(:Decision)-[:ON]->(:Proposal)` with the control, requirement, reviewer and reason, so an agent reads what a human already rejected before it proposes. `crosswalk review` lists pending proposals and records each approve or reject in one transaction: it sets the proposal status, writes a `Decision` and a `Change`, and for an approved `map` creates the `SATISFIES` edge.

```
crosswalk decisions                   # 4 decisions in the committed store
crosswalk decisions --about CTRL-AOTP-11
crosswalk review --list               # 4 pending proposals in the committed store
crosswalk review --approve PR-005 --reason "..." [--store DIR]
```
