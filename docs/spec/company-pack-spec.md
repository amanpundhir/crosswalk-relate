# Spec: control library, company pack, ground truth (architect-owned)

Status: v1.1, 2026-11-22 (1-hop inheritance, blast radius defined). Concrete ids for S1 to S8 are in `inputs/company/PLANTED.md`. C-VPN-REVIEW is `CTRL-AOTP-4`, the closest library wording, because no template says "VPN accounts". Workers implement; the architect reviews. Every change to this spec goes through the architect.

## 0. Fixed facts from day-1/day-2 profiling

- 800-53 Rev 5.2.0: 300 active base controls plus 714 active enhancements. 800-171 Rev 3: **97** active requirements, 17 families. CSF 2.0: 106 active subcategories. Withdrawn entries are dropped.
- Normalised ids: `800-53:AC-2`, `800-53:AC-2(1)`, `800-171:03.01.01`, `CSF:GV.OC-01`.
- Crosswalk edges (`EQUIVALENT_TO`):
  - CSF→800-53: 740 pairs. The source file has no relationship types, so use `kind:'informative-reference'`.
  - 800-171→800-53: the union of the CUI overlay (156) and the OSCAL links (157). Tag each edge with `source: overlay|oscal|both`.
  - CSF→800-171: 310 direct pairs.
  - Drop refs to withdrawn or unknown controls and bare family codes, and log them to `out/ingest-warnings.txt`.
- Templates: StrongDM comply at `aab48494`, 27 policies, ~430 candidate controls (see docs/day2/templates-profile.md).

## 1. The demo date

`as_of: 2026-12-02` (in `inputs/company/company.yaml`). All "expired", "expiring in N days" and "last week" logic uses `as_of`, **never the system clock**. That keeps builds and tests deterministic.

## 2. Control library (code: `src/crosswalk/sources/comply.py`)

- Deterministic split rule from templates-profile.md:
  - Skip the Purpose, Scope, Background, References and Appendix sections.
  - A control is every `i.` item with its `1.` children folded in, plus every `a.` item that has no children.
- Each control gets:
  - an id `CTRL-<ACRONYM>-<n>` (file order, starting at 1);
  - `policy` (acronym), `title` (first ~80 chars, cleaned), `text` (full, with markdown stripped);
  - `text_sha` (sha256 of the normalised text, first 12 hex chars);
  - `vague: bool`. Use the heuristic from the profile: under 8 words, cross-reference only, or a phase label.
- Output: the function returns a list of dicts. `python -m crosswalk.sources.comply --dump` writes `out/control_library.json`, which is not committed.
- Test: same input gives the same ids and hashes. At least 400 controls. Spot-check 3 known ids against the text.

## 3. Company pack: "Harbor & Pine (fictional)", `inputs/company/*.yaml`

| File | Content | Size |
|---|---|---|
| `company.yaml` | name, `as_of`, a disclaimer that everything is fictional | 1 |
| `people.yaml` | id `P-<slug>`, name (clearly fictional), team, role. Must include **Maya Chen** (security lead) and **Dana Okafor** (IT admin; sole owner of 6 controls). | 15 |
| `systems.yaml` | id `SYS-<slug>`, name (generic: "Production database", "Identity provider", "Admin VPN", "Laptop fleet", "Source code host", "CI pipeline", "Central logging", "Backups", "HR system", "Ticketing", …), criticality high/med/low, data_class | 25 |
| `controls.yaml` | **adopted** controls: `id` (from the library), `owners` [person ids], `applies_to` [system ids], `status` implemented/partial/planned. Include no vague controls. Cover at least 12 of the 25 policies. | 60 |
| `evidence.yaml` | id `EV-001`…, kind (screenshot/config-export/report/ticket/attestation), `proves` [control ids], `owner`, `collected_at`, `expires_at` (dates), `location` (fake path) | 120 |
| `audits.yaml` | `AUD-171` 800-171 assessment 2027-01-15. `AUD-53` 800-53 moderate internal review 2027-02-20. `AUD-CSF` CSF 2.0 board self-assessment 2027-03-31. Each has `requests` [evidence ids]. | 3 |
| `mappings.yaml` | Approved `SATISFIES` edges: control → requirement id, `approved_by`, `approved_at`. Mostly to **800-53** (the company did 800-53 work first). A few direct to 800-171. **None to CSF** (so `adopt CSF` shows inherited coverage). | ~120 to 180 |
| `proposals.yaml` | Seed `PROPOSED` mappings (not approved), with `by` (agent name), `rationale` and `created_at` | ~8 |
| `decisions.yaml` | Seed past human decisions on proposals, including **one rejection by Maya on 2026-11-25** with a reason | ~4 |
| `legacy_tracker.csv` | The company's old spreadsheet: control id, requirement ids (`;`-separated), owner name, status text ("Compliant ✔" / "In progress" / "Gap"), last_reviewed. **Deliberately stale** in the planted rows (§4). Used as the "agent with spreadsheets" baseline. | ~60 rows |

Realism rules:
- Mappings must be **plausible**: an MFA control maps to IA-2(1)/IA-2(2), not to PE-3.
- Evidence dates spread over 2026-01 to 2026-11.
- Expiries: mostly 12 months after collection, some 6 or 3 months.

## 4. Planted scenarios (each needs a stable id; tests assert each one)

| Id | Scenario | Exact facts to plant |
|---|---|---|
| S1 **live catch** | The MFA control looks covered but isn't | The adopted MFA control (call it MFA-CTRL, picked from the library) has exactly one evidence item, **EV-044**, which `expires_at: 2026-12-01`. `legacy_tracker.csv` says "Compliant ✔" for it. A second control, CTRL-X, has a mapping to `800-171:03.05.03` that exists **only in proposals.yaml**. So 03.05.03 has no approved, valid path. |
| S2 expiring before audit | 3 evidence items expire between `as_of` and 2027-01-15 | Each is the **only** valid evidence for its control. Together they break **9** 800-171 requirements across **AUD-171 and AUD-53** (through the crosswalk). |
| S3 single owner | Dana is the sole owner of 6 controls touching high-criticality systems | — |
| S4 rejected suggestion | Maya rejected control C-VPN → `800-53:AC-17` on 2026-11-25, reason "AC-17 is remote access; this control is local account review" | A new control C-VPN-REVIEW ("Quarterly review of VPN accounts") is **in the library but not adopted**. It is used live in the Flow B demo. |
| S5 inherited coverage | Some 800-171 gaps are covered only through the 800-53 mappings plus the crosswalk | No direct 171 mapping. Record the expected count as an oracle output. |
| S6 decoy | Evidence that **expired but has a valid replacement** for the same control | It must **not** be flagged by blast radius (a false-alarm test). |
| S7 duplicate evidence | One evidence item that proves controls which satisfy requirements in **all 3 frameworks** | It is the top of the reuse ranking. |
| S8 unowned control | One adopted control with `owners: []` | — |

## 5. Ground truth (`eval/`): written **before** any Cypher

- `eval/oracle.py`: a **pure-Python** oracle with no Relate. It loads the YAML plus the normalised NIST ids and crosswalk pairs, and computes the expected answers:
  - Q1 coverage per framework, with the gap list
  - Q2 adopt (inherited via `EQUIVALENT_TO` up to 2 hops)
  - Q3 blast radius for 30 days and up to the audit date
  - Q4 reuse ranking
  - Q6 owner risk

  Definitions (must match the Cypher later):
  - A requirement is **covered** if some adopted control has an approved `SATISFIES` to it **and** at least one evidence item with `expires_at > as_of` proves that control.
  - For a non-800-53 framework, a requirement is **inherited** if it is not covered directly but a **1-hop** `EQUIVALENT_TO` neighbour is covered directly. (v1.1 architect decision: 2 hops through CSF informative references was too loose. Pack profiling showed 15 direct, 23 inherited at 1 hop, and 55 at 2 hops.)
  - **Blast radius** (Q3) = requirements that are covered directly now and would **lose direct coverage** once the evidence expiring in the window is gone. For each one, also report whether it would still be inherited, so the agent can say "broken, but still met via X". S2's 9 requirements are counted under this definition.
- `eval/ground_truth.json`: the oracle output, committed. Tests compare the Cypher results with it.
- `eval/planted.yaml`: S1 to S8, with ids and the exact expected facts.
- `eval/golden_questions.yaml`: 20 natural-language questions, each with an `expected` answer (taken from the oracle), `must_cite` (node ids that must appear in the cited paths) and `trap` (which planted scenario it probes, if any). Include at least 6 trap questions (S1, S2, S6, S4, S8, S5).
- `eval/bad_proposals.yaml`: 8 proposals the verifier must reject, each with an `expected_reason`. Kinds: duplicate, non-existent target, withdrawn target, previously rejected (S4), wrong framework, evidence request for non-expiring evidence, unknown person, self-contradicting status.
- `eval/control_labels.yaml`: hand labels for **40 adopted controls**. Each gets its correct 800-53 targets: `primary` (1 to 3) plus `acceptable` (others), and a one-line rationale. **Labels must not be copied from `mappings.yaml`.** The labeller works only from the control text and the 800-53 titles and statements. Mark the file header honestly: "labelled with AI assistance from control text and 800-53 statements; reviewed by the architect".

## 6. Acceptance (the architect checks)

- `python -I eval/oracle.py` reproduces ground_truth.json byte for byte.
- Each S1 to S8 is asserted by a pytest in `tests/test_planted.py` against the oracle. The Cypher-based tests come later.
- Every person, system, control and evidence id referenced anywhere exists, checked by a pack-lint test.
- No real company or person names appear. Everything is labelled fictional.
