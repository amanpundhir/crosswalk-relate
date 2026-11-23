# Day 2 data profile: NIST inputs

Profiled 2026-11-22 from the files in `inputs/nist/raw/` (retrieval details and hashes are in `inputs/nist/SOURCES.md`). Throwaway profiling scripts are in `.scratch/nist/`. Everything below was checked by running code on the files unless marked **UNVERIFIED**.

| File | Bytes | Kind |
|---|---|---|
| NIST_SP-800-53_rev5_catalog.json | 10,448,237 | OSCAL catalog (pretty JSON) |
| NIST_SP800-171_rev3_catalog.json | 905,717 | OSCAL catalog |
| NIST_CSF_v2.0_catalog.json | 341,930 | OSCAL catalog |
| csf2.xlsx | 146,546 | CSF 2.0 Reference Tool export (xlsx) |
| sp800-171r3-cui-overlay.xlsx | 121,361 | NIST CUI overlay (xlsx) |

## Headline findings

1. **SP 800-171 Rev 3 has 97 requirements, not 110.** The OSCAL catalog holds 130 requirement entries: 97 active plus 33 withdrawn stubs (Rev 2 numbers kept as `status=withdrawn`). Ingest must drop anything with a `status` prop. The plan's "110" is wrong (it is the Rev 2 count).
2. **csf2.xlsx has no relationship-type column.** It is a flat list of "Source: id" lines per subcategory. There is no subset/superset/equal value anywhere. Pairs only.
3. csf2.xlsx lists both `SP 800-53 Rev 5.1.1` and `SP 800-53 Rev 5.2.0` lines. The OSCAL catalog is Rev 5.2.0, so use the 5.2.0 lines only.
4. The overlay xlsx and the OSCAL 800-171 catalog both carry 800-53 links per requirement and agree on 153 of about 157 pairs.
5. The CSF OSCAL catalog and csf2.xlsx both include withdrawn CSF 1.1 stubs: 185 subcategory rows, of which 106 are real CSF 2.0 subcategories.
6. Ids in the CSF OSCAL catalog are uppercase (`GV.OC-01`), not lowercase as the day-1 licence note guessed.

---

## 1. NIST_SP-800-53_rev5_catalog.json

**Structure.** `catalog` has `uuid`, `metadata`, `groups` (20 families), `back-matter` (202 resources). `metadata.version = 5.2.0`, `oscal-version 1.2.3`, `last-modified 2026-10-22`. No top-level `controls`. Each group is `{id, class, title, props, controls[]}`. A base control has `class: SP800-53`. Enhancements are **nested** in the parent's `controls[]` with `class: SP800-53-enhancement` (one nesting level only).

**Control keys.** `id, class, title, props, links` (1191 of 1196), `parts` (1016), `params` (679), `controls` (183 parents).

**Id formats (raw).** Family `ac`. Base `ac-2`, `ia-5`, `sc-7`. Enhancement `ac-2.1`, `ac-2.13`, `sc-7.4` (dot, no padding). All 1196 ids match `^[a-z]{2}-\d+(\.\d+)?$`. Useful props per control: `label` (several: `AC-2` plain, `AC-02` with class `zero-padded`, `AC-02` class `sp800-53a`), `sort-id` (`ac-02.01`), `implementation-level`, `status` (only on withdrawn).

**Counts.**

| Item | Total | Withdrawn | Active |
|---|---|---|---|
| Families | 20 (AC AT AU CA CM CP IA IR MA MP PE PL PM PS PT RA SA SC SI SR) | 0 | 20 |
| Base controls | 324 | 24 | 300 |
| Enhancements | 872 | 158 | 714 |
| All | 1196 | 182 | 1014 |

Withdrawn entries have only `props` (with `status: withdrawn`) and `links` with `rel=incorporated-into` (166) or `moved-to` (34), for example `ac-2.10` links to `#ac-2_smt.k`. Filter them out at ingest.

**Where human-readable text lives.** `parts[]` of each active control (every non-withdrawn control has a `statement`):
- `statement` (`ac-2_smt`): the requirement text. Either top-level `prose` (798 controls, typical for enhancements) or nested `item` parts with `label` props `a.`, `1.`, `(a)` (218 controls without top-level prose). Items nest several levels.
- `guidance` (`ac-2_gdn`): the supplemental guidance, a single `prose` string with `\n\n` paragraph breaks (1014 controls).
- `assessment-objective` and `assessment-method` (SP 800-53A text): present but not needed.
- `links`: `rel=related` (3512 control-to-control, `#ac-3`), `required` (enhancement to parent), `reference` (to back-matter).

**Placeholders.** Only in `statement` (and assessment parts), never in `guidance`. Form: `{{ insert: param, ac-02_odp.01 }}` (1207 occurrences in statements). The id resolves to an entry in the control's own `params[]` (1600 params in total). 1204 of 1207 resolve in the control's own `params`. Three live in a sibling: `ia-13.3` uses `ia-13_odp.01`, `sc-42.2` uses `sc-42.01_odp`, `si-10.1` uses `si-10_odp`, all defined on another control. Resolve against a global param map keyed by id.
Each param has `id`, `props` (`alt-identifier` such as `ac-2_prm_1` is the legacy id; some statements use that alias, for example `ac-1_prm_1`, so index both), and either `label` (1467, such as "frequency") or `select` (133, `{how-many, choice[]}`). Also `guidelines[].prose`. Suggested rendering: `[Assignment: <label>]` or `[Selection (<how-many>): a; b; c]`, the same bracket style the overlay xlsx uses.
Example: `Require {{ insert: param, ac-02_odp.01 }} for group and role membership;` becomes `Require [Assignment: prerequisites and criteria] for group and role membership;`.

**Back-matter.** 202 resources (publication references). Not needed.

---

## 2. NIST_SP800-171_rev3_catalog.json

**Structure.** `catalog` has `groups` (17 families `SP_800_171_03.01` to `03.17`, `class: family`), `back-matter` (224 resources). `metadata.version = 1.1.0`, `oscal-version v1.2.3`, `published 2026-10-22`. Requirements sit directly in `group.controls[]` (`class: requirement`, no nesting).

**Id formats (raw).** Family `SP_800_171_03.01`. Requirement `SP_800_171_03.01.01`, `SP_800_171_03.05.03`, `SP_800_171_03.13.08`. All 130 match `^SP_800_171_03\.\d\d\.\d\d$`. Props: `sort-id` (`03.01.01`), `label` (`Account Management (03.01.01)`, active only), `status=withdrawn`.

**Counts.**
- Entries: 130. Withdrawn: 33 (no `parts`; `title` is just the number, for example `03.01.13`; `links` with `rel=incorporated_into` (24) or `addressed_by` (17), `href` like `03.13.08`, no `#`).
- **Active requirements: 97.** Confirmed.
- Families: 17. Active per family: 03.01 16, 03.02 2, 03.03 8, 03.04 10, 03.05 8, 03.06 5, 03.07 3, 03.08 7, 03.09 2, 03.10 5, 03.11 3, 03.12 4, 03.13 10, 03.14 5, 03.15 3, 03.16 3, 03.17 3.

**Where text lives.** Active requirements have `parts`:
- `statement` (`statement_03.01.01`, `class: security_requirement`): nested `item` parts labelled `SR-03.01.01.a`, `.c.01`. 29 requirements also carry top-level prose, the rest only items. Flatten items depth-first.
- `guidance` (`guidance_D-03.01.01`): one prose string. It contains CPRT markdown links such as `[](#/cprt/framework/version/SP_800_171_3_0_0/home?element=03.01.02)03.01.02`; strip the `[](...)` part.
- `assessment-objective` (422, with `links rel=assessment-for` back to the `SR-...` item) and `assessment-method` (281): the 171A text, optional.
- `params` (88 across 50 requirements): ids like `A.03.01.01.ODP.01`, fields `label`, `usage`, `guidelines`; 3 have `select`.

**Placeholders.** Same syntax: `{{ insert: param, A.03.04.06.ODP.01 }}`. 80 occurrences in statements (in 72 prose fragments) and 97 prose fragments with placeholders in assessment objectives. All 80 statement placeholders resolve in the requirement's own `params`. Select choices can themselves contain a nested `{{ insert: ... }}`, so resolve recursively.

**800-53 links inside this file.** Each active requirement's `links[]` (`rel=reference`, 356 in total) point at `back-matter` resources. Many of those resources are 800-53 controls: `title` is a zero-padded id (`AC-02`, `AC-02(03)`) and `rlinks[0].href` is a CPRT URL (`...version/SP_800_53_5_1_1/home?element=AC-02`, that is Rev 5.1.1). The rest are other publications (`SP 800-xx`, `IR xxxx`). Filtering resource titles with `^[A-Z]{2}-\d\d(\(\d\d\))?$` gives **157 (800-53 control, 171 requirement) pairs covering all 97 requirements**. There is no relationship-type value, only `reference`.

---

## 3. NIST_CSF_v2.0_catalog.json

**Structure.** `catalog.groups` = 6 functions (`class: function`, ids `GV ID PR DE RS RC`) with `controls[]` = categories (`class: category`) with `controls[]` = subcategories (`class: subcategory`). `metadata.version 1.2.1`. `back-matter` has 4 resources (not useful).

**Id formats (raw, uppercase).** Function `GV`. Category `GV.OC`, `PR.AA`, `RS.MA`. Subcategory `GV.OC-01`, `PR.AA-03`, `DE.CM-09`. `title` of a subcategory equals its id; the text is in `parts`.

**Counts.**

| Level | Total | Withdrawn (`status`) | Active |
|---|---|---|---|
| Functions | 6 | 0 | 6 |
| Categories | 34 | 12 | **22** |
| Subcategories | 185 | 79 | **106** |

Active subcategories per function: GV 31, ID 21, PR 22, DE 11, RS 13, RC 8. Withdrawn ones are CSF 1.1 stubs (`ID.BE-01`, `PR.AC-01`...) with `links rel=incorporated_into` or `moved_to` pointing to the new id. Drop them.

**Text.** `parts`: `statement` (the outcome sentence, for functions the part is called `overview`), and `guidance` with `class: example` (one part per implementation example, 363 in total, id `GV.OC-01.001`). Props: `marking` (`risk-party` 1st/3rd, 125), `sort-id`, `label`. No `{{ }}` placeholders, no params.

---

## 4. csf2.xlsx (CSF 2.0 Reference Tool export)

**Sheets.** `Introduction` (5 rows x 2 columns: Title, Read Me, Change Log `Final`, Generated Date 2026-11-22 07:55:08) and `CSF 2.0` (233 rows x 5 columns). openpyxl warns "no default style" (harmless).

**Header.** Row 1 is a merged-style banner (cell B1 holds "The NIST Cybersecurity Framework 2.0 / www.nist.gov/cyberframework"). **Row 2 is the header**, data starts at row 3. Exact column names:
`Function`, `Category`, `Subcategory`, `Implementation Examples`, `Informative References`.

**Layout.** One hierarchy row per element, with the text in the column of its level: Function rows (col A, `GOVERN (GV): The organization's ...`), Category rows (col B, `Organizational Context (GV.OC): The circumstances ...`), Subcategory rows (col C, `GV.OC-01: The organizational mission is understood ...`). Function rows also repeat as empty trailer rows (`GOVERN (GV)`, no refs). Contents: 6 real function rows, 34 category rows (22 active + 12 `[Withdrawn: ...]`), 185 subcategory rows (106 active + 79 withdrawn), the same as the OSCAL catalog.

**Samples** (columns truncated):

| Row | Col | Value |
|---|---|---|
| 3 | A / E | `GOVERN (GV): The organization's cybersecurity risk management...` / `CRI Profile v2.0: GV\nCSF v1.1: ID.GV\nISO/IEC 27001:2022: Man...` |
| 5 | C / D / E | `GV.OC-01: The organizational mission is understood and informs cybersecurity risk management` / `Ex1: Share the organization's mission (e.g., ...` / `BXAIOS: Chapter 2 ...\nCCMv4.0: BCR-01\n...\nSP 800-53 Rev 5.1.1: PM-11\nSP 800-53 Rev 5.2.0: PM-11\n...` |
| 6 | C | `GV.OC-02: Internal and external stakeholders are understood, ...`; E includes `SP 800-171 Rev 3: 03.11.01`, `SP 800-53 Rev 5.2.0: PM-09`, `...: SR-03` etc. |

**Informative References cell format.** One cell per row, lines separated by `\n`, each line `"<Source name>: <id>"`, split on the first `": "`. 21 source names appear on subcategory rows. The ones that matter: `SP 800-53 Rev 5.2.0` (740 lines), `SP 800-53 Rev 5.1.1` (734), `SP 800-171 Rev 3` (310), `CSF v1.1` (156). Others (CCMv4.0, NICE Framework, PCI DSS, ISO/IEC 27001, CRI Profile v2.0, SCF, AISVS, SDOS, OWASP LLM, SP-800-37, SP 800-221A, CIS v8.x, CoP, SP 800-81r3, Guardian-SDK, SSDF, IRP, BXAIOS, Five Laws, AI-SOC) are ignored. Third-party ids (ISO, PCI, CIS) must not be copied into the repo, since only NIST mappings are in scope. Some lines have no `": "` value or are truncated (`ISO/IEC 27001:2022: Annex A Controls:`); irrelevant for NIST sources.

**Relationship / rationale column: none.** There is no column or inline text with a relationship type (searched for subset/superset/equal/intersect: zero hits). Distinct relationship values: **none**.

**SP 800-53 Rev 5 rows.** On the 106 active subcategories: Rev 5.2.0 has 740 (subcategory, control) lines, every active subcategory has at least one (min 1, up to 12+). All 740 lines are unique per subcategory. 737 are control-level ids (`PM-11`, `SA-10(01)`, 18 of them enhancements) and 3 are bare family codes (`PT` on GV.OC-03, `CP` and `IR` on PR.IR-03). Category and function rows also carry references (2 category rows with 6 Rev 5.2.0 lines); ignore them or ingest them at category level only. Rev 5.1.1 vs 5.2.0 differs by 7 lines (5.2.0 adds `DE.AE-06` to `RA-04`, `GV.RM-03`/`PR.IR-03`/`PR.PS-06` to `SA-24`, `PR.PS-04`/`PR.PS-06` to `SA-15(13)`, `RS.AN-03` to `SI-02(07)`; 5.1.1 has `DE.AE-06` to `RA-03` which 5.2.0 dropped). One 5.2.0 line (`DE.AE-06` to `RA-04`) points at a control the 5.2.0 OSCAL catalog marks withdrawn (`ra-4`, incorporated into `ra-3`). Reason UNVERIFIED.

**SP 800-171 Rev 3 rows (bonus).** 310 (subcategory, requirement) lines covering 89 of the 106 subcategories and 69 distinct requirements. Ids are already in `03.15.01` format.

### Answer (a): CSF 2.0 subcategory to 800-53 pairs and relationship types

Read sheet `CSF 2.0` from row 3. For each row with a non-empty `Subcategory` cell that does not contain `[Withdrawn`, take `sub_id = Subcategory.split(":")[0]` (for example `GV.OC-01`). Split `Informative References` on `\n`, keep lines starting with `SP 800-53 Rev 5.2.0: `, and take the text after the prefix as the control id (zero-padded, `AC-02(01)` form). That yields 740 pairs, of which 737 resolve to a control or enhancement in the OSCAL catalog (3 are family-level, 1 targets a withdrawn control, so 736 clean pairs). **No relationship types exist in this file.** Store the edge as `relationship = "informative-reference"` (meaning "unspecified"). If typed OLIR relationships (subset of, intersects with, ...) are needed, they are not in this download; the OLIR catalog entry from the day-1 note would have to be fetched separately (UNVERIFIED whether it offers typed rows).

---

## 5. sp800-171r3-cui-overlay.xlsx

**Sheets.** `CUI Overlay Overview` (empty: 1 row x 1 column, no content) and `CUI Overlay` (1139 rows x 7 columns, 1138 data rows). No merged cells.

**Header (row 1), exact names.** `Unique Sort ID (800-53r5)`, `SP 800-53 Rev 5 Control & Control Enhancement`, `Tailoring Decision`, `Unique Sort ID (800-171r3)`, `SP 800-171 Rev 3 Security Requirement`, `Additional Tailoring ` (trailing space), and a 7th column with no header that is always empty.

**Granularity.** One row per 800-53 statement item, grouped under header rows (item `00` = the control or enhancement itself). Sort id pattern `FF-NN-EE-II`: family, control number, enhancement number (`00` = base control), item index. So `AC-02-00-00` is the AC-2 header, `AC-02-01-00` is the AC-2(1) header, `AC-02-00-03` is item 3 of AC-2. 284 enhancement header rows, 285 header rows in total with a title. Data glitch: one id is malformed, `AT-01-00-5` (should be `-05`); parse with `\d+` for the last group. The 171 sort id looks like `03-01-01:` (requirement header), `03-01-01a.` (item), `03-01-01a.01`. About 580 rows have a blank placeholder in this column (` `, empty, or the text `�`), meaning no 171 target.

**Samples.**

| 800-53 sort id | 800-53 text | Decision | 171 sort id | 171 text | Additional Tailoring |
|---|---|---|---|---|---|
| AC-01-00-00 | AC-01  Policy and Procedures | CUI | 03-15-01: | 03.15.01  Policy and Procedures | (blank) |
| AC-01-00-01 | a. Develop, document, and disseminate to [Assignment: organization-defined personnel or roles]... | CUI | 03-15-01a. | 03.15.01.a. Develop, document, and disseminate to organizational personnel or roles the po... | Addresses all policy (instead of only access control policy) Removed ODP to assign ... |
| AC-01-00-03 | (a) Addresses purpose, scope, roles, ... | NCO | ` ` | `�` | (blank) |

**Tailoring Decision values (distinct).** `CUI` 558, `NCO` 458 (+1 row with a trailing space, `NCO `, so strip), `FED` 75, `ORC` 46. Expansions of the codes are **UNVERIFIED** (the Overview sheet is empty). Only `CUI` rows can carry a 171 target (554 of 558; the other 4 are blank, namely `AC-02-05-00`, `CM-12-00-02`, `RA-07-00-01`, `SA-08-00-01`). `NCO`, `FED` and `ORC` rows never link to a 171 requirement. The `Additional Tailoring` column is free text describing wording changes (`Removed ODPs to assign "frequency" and "events"`, `Rephrased; no change in outcome`, `Updated title to reflect merged controls`, ...), populated for 304 rows; it is not a relationship type.

**How many rows link to SP 800-53 Rev 5.** Every row (1138) is an 800-53 Rev 5 item, covering 288 distinct control and enhancement ids. Rows with a 171 target: **554**. Collapsed to (control, requirement) pairs: **156 pairs, 97 distinct requirements (all active ones), 156 distinct 800-53 ids (111 base, 45 enhancements)**, each 800-53 id mapping to exactly one requirement and each requirement to 1 to 17 controls (median 1). Four overlay control ids are absent from the Rev 5.2.0 catalog (`IA-06(06)`, `SI-05(05)`, `SI-11(01)`, `IA-07(06)`), which leaves 154 usable pairs; the first two are in linked pairs (`IA-06(06)` to 03.05.11, `SI-05(05)` to 03.14.03). Reason UNVERIFIED (possible typos for `IA-6(5)`-style numbers).

### Answer (b): 800-171 r3 requirement to 800-53 pairs

Two usable sources, which mostly agree.
1. **Overlay xlsx** (richer, and the official tailoring decision). For each data row where `Tailoring Decision.strip() == "CUI"` and col D matches `^(\d\d)-(\d\d)-(\d\d)`, requirement = `NN.NN.NN` and control = family + number from col A (`AC-02-01-00` gives `AC-2(1)`). De-duplicate to pairs: 156 pairs, 97 requirements.
2. **OSCAL 171 catalog.** For each active requirement, resolve each `links[].href` (`#uuid`) through `back-matter.resources`, keep resources whose title matches `^[A-Z]{2}-\d\d(\(\d\d\))?$`, then strip the zero padding: 157 pairs, 97 requirements.
Overlap: 153 pairs in both. OSCAL only: `AU-09(04)`->03.01.05, `IA-06`->03.05.11, `SC-28`->03.08.05, `SI-05`->03.14.03. Overlay only: `AC-17(02)`->03.13.08, `IA-06(06)`->03.05.11, `SI-05(05)`->03.14.03. Recommendation: use the union, tag each edge with `source` (`NIST-OVERLAY`, `NIST-OSCAL`, or both) and treat the intersection as higher confidence. Direction in the NIST data is 800-53 to 171 (the 171 requirement is derived from the 800-53 control); the graph edge can be undirected `EQUIVALENT_TO` with `relationship="tailored-from"` for the overlay (no equivalence strength is given) and `relationship="reference"` for OSCAL. NIST itself says such mappings are a general indication, not proof of equivalence.

---

## 6. Recommended normalised ids

Common rule: framework prefix, colon, then the display form used in NIST's own prose (upper case, no zero padding for 800-53, zero padding kept for 800-171 because it is part of the official number). Family node ids use the same scheme.

| Framework | Normalised id | Examples | Transform from raw |
|---|---|---|---|
| 800-53 control | `800-53:AC-2` | `800-53:AC-2`, `800-53:SC-7`, `800-53:PM-11` | OSCAL `ac-2`: `id.upper()` |
| 800-53 enhancement | `800-53:AC-2(1)` | `800-53:AC-2(1)`, `800-53:AC-2(13)`, `800-53:SC-7(4)` | OSCAL `ac-2.1`: `re.sub(r'\.(\d+)$', r'(\1)', id.upper())` |
| 800-53 family | `800-53:AC` | `800-53:AC`, `800-53:SR` | OSCAL group `id.upper()` |
| 800-171 requirement | `800-171:03.01.01` | `800-171:03.01.01`, `800-171:03.05.03`, `800-171:03.13.08` | OSCAL `SP_800_171_03.01.01`: strip prefix `SP_800_171_`; overlay col D `03-01-01a.`: take first three 2-digit groups and join with `.` |
| 800-171 family | `800-171:03.01` | `800-171:03.01`, `800-171:03.13` | OSCAL group `SP_800_171_03.01`: strip prefix |
| CSF subcategory | `CSF:GV.OC-01` | `CSF:GV.OC-01`, `CSF:PR.AA-03`, `CSF:DE.CM-09` | OSCAL id as-is (already upper); csf2.xlsx `Subcategory.split(":")[0]` |
| CSF category | `CSF:GV.OC` | `CSF:GV.OC`, `CSF:RS.MA` | OSCAL id as-is |
| CSF function | `CSF:GV` | `CSF:GV`, `CSF:RC` | OSCAL group id as-is |

Transforms from the secondary formats to the 800-53 form:
- csf2.xlsx and OSCAL-171 back-matter titles (`AC-02`, `AC-02(01)`): `re.fullmatch(r'([A-Z]{2})-(\d\d)(?:\((\d\d)\))?')` then `f"800-53:{fam}-{int(n)}" + (f"({int(e)})" if e else "")`. `PM-11` -> `800-53:PM-11`, `SA-15(13)` -> `800-53:SA-15(13)`.
- Overlay col A `AC-02-01-05`: `re.fullmatch(r'([A-Z]{2})-(\d\d)-(\d\d)-(\d+)')`, enhancement = group 3 (`00` means none), ignore the item index.

Join key for the loader: `800-53:ac-2.1` (OSCAL) and `800-53:AC-2(1)` (normalised) round-trip with the regexes above. Validate every pair endpoint against the set of active catalog ids and report the unresolved ones (3 family-level CSF refs, 1 withdrawn, 4 overlay ids not in the catalog) instead of silently dropping them.

## Not verified

- Meaning of overlay codes `NCO`, `FED`, `ORC` (Overview sheet is empty).
- Why the overlay contains 4 control ids absent from Rev 5.2.0, and why csf2.xlsx maps `DE.AE-06` to a withdrawn control.
- Whether an OLIR-typed CSF 2.0 to 800-53 file with relationship values exists as a download (not fetched).
- Licence wording for the two xlsx files (day-1 note stands; no licence text inside the files).
