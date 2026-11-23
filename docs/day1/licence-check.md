# Day 1 licence check (data sources and policy templates)

Checked 2026-11-22 by reading web pages, the GitHub API and raw LICENSE/README text. No datasets were downloaded. This is a factual review, not legal advice. Anything not verified is marked **UNVERIFIED**.

## Summary table

| # | Source | URL | Format | Licence / terms | Redistribute in Apache-2.0 public repo? | Attribution |
|---|---|---|---|---|---|---|
| A | SP 800-53 Rev 5 catalog (OSCAL) | https://github.com/usnistgov/oscal-content/tree/main/nist.gov/SP800-53/rev5/json | JSON (also XML, YAML) | Public domain (US gov work) plus CC0 1.0 waiver, in the repo's LICENSE.md | Yes | None legally required; NIST asks to be credited as source |
| B | SP 800-171 Rev 3 | https://github.com/usnistgov/oscal-content/tree/main/nist.gov/SP800-171/rev3/json | OSCAL JSON (also XML, YAML); CPRT xlsx/JSON export | Same repo licence (CC0); CPRT pages show no licence text | Yes (OSCAL file). CPRT export: yes under the NIST 17 USC 105 position, UNVERIFIED on the site itself | Credit NIST |
| C | CSF 2.0 | https://github.com/usnistgov/oscal-content/tree/main/nist.gov/CSF/v2.0/json | OSCAL JSON; CPRT xlsx/JSON | Same repo licence (CC0) | Yes | Credit NIST |
| D1 | CSF 2.0 to SP 800-53 Rev 5 (informative references) | https://csrc.nist.gov/extensions/nudp/services/json/csf/download?olirids=all (saved as csf2.xlsx) ; catalog entry "CSFv2.0-to-SP-800-53-Rev-5-2-0" at https://csrc.nist.gov/projects/olir/informative-reference-catalog/details?referenceId=186 | xlsx | No licence text on the page; falls under NIST general policy | Likely yes (NIST-authored); UNVERIFIED wording | Credit NIST |
| D2 | SP 800-171 Rev 3 to SP 800-53 Rev 5 | https://csrc.nist.gov/files/pubs/sp/800/171/r3/final/docs/sp800-171r3-cui-overlay.xlsx (121 KB) ; also the CPRT dataset and Appendix C of the PDF | xlsx | NIST publication (17 USC 105) | Likely yes | Credit NIST |
| E | NIST copyright position | https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications | web page | 17 USC 105 in the US; foreign copyright may apply | n/a | n/a |
| F | JupiterOne security-policy-templates | https://github.com/JupiterOne/security-policy-templates | Markdown templates (`.md.tmpl`) plus JSON | CC BY-SA 4.0 (share-alike) | Only as a separate, unchanged-licence directory; adaptations must stay CC BY-SA 4.0 | Credit JupiterOne, link licence, indicate changes |
| G | StrongDM comply | https://github.com/strongdm/comply | Markdown with YAML front matter | Apache-2.0 (whole repo, single LICENSE.txt) | Yes | Keep licence and notice, mark changes |
| H | Other | none suitable found | | | | |

## A. NIST SP 800-53 Rev 5 (OSCAL JSON)

- Repo: https://github.com/usnistgov/oscal-content (not archived, last push 2026-10-27). GitHub shows the licence as "Other / NOASSERTION" only because the file is custom.
- Path: `nist.gov/SP800-53/rev5/json/`. Main file `NIST_SP-800-53_rev5_catalog.json` (10.4 MB pretty; `-min.json` 4.9 MB). Also baselines (LOW, MODERATE, HIGH, PRIVACY) as profiles and resolved-profile catalogs (0.8 to 4.6 MB each).
- Raw URL: https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json
- Version: the README says the folder tracks Rev 5, with 800-53 release 5.2.0 referenced. Check the catalog's `metadata.version` after download (UNVERIFIED which minor release the JSON is).
- Licence text: https://github.com/usnistgov/oscal-content/blob/main/LICENSE.md. Quote: "this project is in the public domain within the United States". It also says NIST waives copyright worldwide "through the CC0 1.0 Universal public domain dedication". LICENSE.md also links a "National Institute of Standards and Technology License" (the NIST software/data disclaimer; its text was not in the 27-line file I read).
- Size: about 1,190 controls and enhancements (from general knowledge, UNVERIFIED count).
- Gotchas: the pinned release v1.4.0 is also referenced by NIST (https://github.com/usnistgov/oscal-content/tree/v1.4.0/src/nist.gov/SP800-53). Pin a commit or tag in SOURCES.md. Control text uses `{{ insert: param, ... }}` placeholders that need resolving. Use the pretty-printed file for readable diffs.

## B. NIST SP 800-171 Rev 3

- Best official machine-readable source: OSCAL at https://github.com/usnistgov/oscal-content/tree/main/nist.gov/SP800-171/rev3/json, file `NIST_SP800-171_rev3_catalog.json` (906 KB; min 529 KB). Same CC0 licence as A.
- Official alternative: the CPRT dataset https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_171_3_0_0/home. NIST says the CPRT offers XLSX and JSON downloads (https://csrc.nist.gov/projects/cprt/data-formats). CPRT JSON has four top-level elements: documents, elements, relationships, relationship_types. Schema: `/csrc/media/Projects/cprt/documents/schema/cprt_schema.json` on csrc.nist.gov. No direct data URL is published; the download is a button in the web app (UNVERIFIED exact URL).
- Publication page: https://csrc.nist.gov/pubs/sp/800/171/r3/final. Also lists the CUI Overlay xlsx and the Rev 2 to Rev 3 analysis xlsx (https://csrc.nist.gov/files/pubs/sp/800/171/r3/final/docs/sp800-171r2-to-r3-analysis.xlsx, 53 KB).
- Size: 97 requirements in Rev 3 (general knowledge, UNVERIFIED here). Note Rev 2 had 110, and the project plan says 110. Rev 3 is not 110. **Fix the plan and the "110 requirements" demo copy, or use Rev 2.**
- Gotcha: CMMC currently still uses Rev 2 (DARPA training deck states Rev 3 is not currently implemented for CMMC). Rev 3 adds organisation-defined parameters.

## C. NIST CSF 2.0

- OSCAL: https://github.com/usnistgov/oscal-content/tree/main/nist.gov/CSF/v2.0/json, file `NIST_CSF_v2.0_catalog.json` (342 KB; min 165 KB). Licence as in A.
- Official alternative: CPRT https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/CSF_2_0_0/home (xlsx/JSON).
- Size: 6 functions, 22 categories, 106 subcategories (general knowledge, UNVERIFIED here).
- Gotcha: OSCAL IDs look like `gv.oc-01`; CSF 2.0 informative references use `GV.OC-01`. Normalise case.

## D. Official crosswalks

1. **CSF 2.0 to SP 800-53 Rev 5**: NIST OLIR catalog entry "CSFv2.0-to-SP-800-53-Rev-5-2-0" (https://csrc.nist.gov/projects/olir/informative-reference-catalog/details?referenceId=186; the share link in the page says referenceid=203, so the id is UNVERIFIED). Download from https://www.nist.gov/cyberframework/csf-20-informative-references: "all informative references" xlsx at https://csrc.nist.gov/extensions/nudp/services/json/csf/download?olirids=all (server sends `content-disposition: attachment;filename=csf2.xlsx`; a HEAD request reported length 0, so the real size is UNVERIFIED). It contains all CSF 2.0 informative references, not only 800-53, so filter the 800-53 rev 5 rows.
   - Columns and relationship values: UNVERIFIED (file not opened). From NISTIR 8278A, OLIR relationship types are subset of, intersects with, equal, superset of, not related to (from memory, not verified on a page I read).
   - NIST warns mappings "provide a general indication" of coverage and are not proof of equivalence (800-53 Rev 5 page, https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final).
2. **Older alternative**: https://csrc.nist.gov/files/pubs/sp/800/53/r5/upd1/final/docs/csf-pf-to-sp800-53r5-mappings.xlsx (202 KB). This maps CSF **1.1** and Privacy Framework to 800-53 Rev 5, not CSF 2.0. Do not use it as CSF 2.0 ground truth.
3. **SP 800-171 Rev 3 to SP 800-53 Rev 5**: no standalone crosswalk spreadsheet is listed on the publication page. Options: (a) `sp800-171r3-cui-overlay.xlsx` (121 KB), which NIST describes as the direct 800-53 control tailoring for each 800-171 requirement; (b) the "Source/Reference" links per requirement in the CPRT dataset and the OSCAL catalog; (c) Appendix C of the PDF https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r3.pdf. Column names in (a) are UNVERIFIED. The OSCAL 800-171r3 catalog may carry the 800-53 links as `links`/`props` (UNVERIFIED).
4. OLIR landing: https://csrc.nist.gov/projects/olir/faqs ; no licence text on that page.

## E. NIST copyright position

- Statement page: https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications. Key points (from fetched summary): works of NIST employees are "not subject to copyright protection in the United States" (17 USC 105). It says foreign copyright may apply: "may be subject to copyright protection in foreign countries". Exception: Standard Reference Data, which Commerce may copyright (15 USC 290e). That does not cover the catalogs above. For data, NIST asks users to "explicitly acknowledge" NIST as the source. The statement does not use the words "public domain" for data; the oscal-content LICENSE.md does.
- General page https://www.nist.gov/oism/copyrights : "may be distributed or copied", with byline credit requested. Material marked copyrighted is excluded.
- Caveat: Technical Series publications may include third-party material that is copyrighted. The 800-53 and 800-171 catalogs are NIST-authored, but the 800-53 mappings to ISO/IEC 27001 were produced under third-party terms. Do not copy ISO text.

## F. JupiterOne security-policy-templates

- Licence: CC BY-SA 4.0 (GitHub API: `CC-BY-SA-4.0`; LICENSE file starts "Attribution-ShareAlike 4.0 International"). https://github.com/JupiterOne/security-policy-templates/blob/main/LICENSE
- Not archived. Last commit 2025-12-09 (PR #170, remove Cortex files). 361 stars. Default branch `main`.
- Structure (under `templates/`):
  - `policies/*.md.tmpl`: 25 policies (access, asset-mgmt, bcdr, breach, ccm, ir, risk-mgmt, sdlc, vendor, vuln-mgmt, ...).
  - `procedures/*.md.tmpl`: 141 procedures (ids like `cp-access-mfa`). These are the natural "controls".
  - `ref/`: reference docs, including `nist-mapping.md.tmpl` (maps NIST SP 800-53 control families, 17 families, to policies; family level only).
  - `config.json`: organisation variables, domains (ids such as AI, PA, VM), policy and procedure registries.
  - `standards/`: framework JSONs, plus `controls-mapping.json`, which maps all 141 procedure ids to framework requirements (NIST CSF **1.1** ids, 95 entries; CIS Controls v8, CSA CCM, HIPAA, PCI DSS, ISO 27002:2013, CMMC ML1, SOC 2, HITRUST). No 800-53 Rev 5 requirement-level mapping. `standards/nist-csf/v2.0.0.json` and `standards/nist-800-53/rev4.json` exist as framework lists.
- Gotchas: files are Mustache templates (`{{companyShortName}}`, `{{#needStandardHIPAA}}`) so rendering is needed. The README says the bundled framework JSONs (CIS, PCI, HITRUST, ISO) are examples and that using them "requires that you have obtained necessary end-user license". Do not copy the `standards/` third-party framework text (ISO, PCI, HITRUST, SOC 2, CIS). Only copy `policies/`, `procedures/` and the mapping ids. Whether JupiterOne can validly relicense third-party-derived text under CC BY-SA is UNVERIFIED.
- Share-alike effect: unmodified copies kept in their own folder are fine. Any adaptation (our Harbor & Pine company pack built from the wording) would be an adaptation licensed CC BY-SA 4.0. CC BY-SA 4.0 is one-way compatible with GPLv3 only; it is not compatible with Apache-2.0 as the licence of the same file.

## G. StrongDM comply

- Licence: Apache-2.0 (GitHub API `Apache-2.0`; LICENSE.txt "Apache License Version 2.0"). https://github.com/strongdm/comply/blob/master/LICENSE.txt . One licence for the repo. The README does not state a separate licence for the templates (the README line says only "open source policy and procedure templates"). I found no separate licence file for `example/`.
- Not archived on GitHub, but effectively dormant: last commit 2022-07-21. Default branch `master`.
- Structure: `example/policies/*.md` (27 policies, each with YAML front matter: `name`, `acronym`, `satisfies: TSC: [CC6.1, ...]`, `majorRevisions`), `example/procedures/*.md` (4: offboarding, onboarding, patch, workstation), `example/narratives/*.md` (5), `example/standards/TSC-2017.yml` (SOC 2 Trust Services Criteria, ids CC1.1 and so on).
- Controls: there is no separate control layer. Policies carry numbered statements, and mappings are to SOC 2 TSC ids only. No NIST mappings.
- Gotchas: `TSC-2017.yml` contains the AICPA SOC 2 criteria wording, which is copyrighted material shipped under the repo licence. Do not copy it (matches the project rule to exclude SOC 2 text). Policy text is dated 2018, informal. The `satisfies` ids are not usable as NIST ground truth.

## H. Other candidates

Verified:
- ComplianceAsCode/content (https://github.com/ComplianceAsCode/content): BSD-3-Clause (LICENSE first line "SPDX license identifier: BSD-3-Clause", Red Hat), active (push 2026-11-21), has `controls/nist_800_171.yml`, `hipaa.yml`, and so on. It is OS/platform hardening rules (RHEL, OpenShift), not SaaS company policies, so it does not fit the "company controls" role. Possible later as machine-checkable control mappings.
- GitLab control templates, SCF, opensecurityarchitecture.org, Secureframe: not verified or not permissive (GitLab handbook is CC BY-SA, SCF is CC BY-ND from memory, others show no licence). UNVERIFIED, not recommended.

No permissively licensed (non share-alike) open-source SaaS policy set with NIST 800-53 mappings was found.

## Recommendation

**Use G (StrongDM comply) as the template set** for the Apache-2.0 repo.

Why: its Apache-2.0 licence lets us adapt the wording freely and ship the Harbor & Pine pack under our Apache-2.0 licence, with only a notice and change marking. F (JupiterOne) is richer, with 141 granular procedures that make better `:Control` nodes, but CC BY-SA 4.0 would force every adapted file, including our company pack text derived from it, to stay CC BY-SA, and it is not Apache-compatible. Its mapping is to CSF 1.1 rather than 2.0.

Trade-off to accept: G has only 27 policies and 4 procedures, so `:Control` text will be policy statements (each lettered clause "a., b., c." can become a Control). Its only mapping is to SOC 2 ids, which we ignore, which is fine since NIST's crosswalk is the ground truth.

Fallback: if the 27 policies give too few controls, add F's `procedures/` as a separate folder `inputs/templates/jupiterone/` under CC BY-SA 4.0, unmodified, loaded as a second source, and do not mix its text into Harbor & Pine files. Decide after the day-1 count.

Do not copy: `example/standards/TSC-2017.yml` (G) and `templates/standards/*` (F).

### Proposed `inputs/templates/NOTICE.md`

```
Policy templates in this folder come from StrongDM comply
(https://github.com/strongdm/comply, directory example/), copyright
StrongDM, Inc. and contributors, licensed under the Apache License 2.0
(https://www.apache.org/licenses/LICENSE-2.0). Files here were copied from
the upstream repository at commit <SHA> on <DATE>. Files marked
"Modified" were changed by the Crosswalk project (formatting and parsing
only; the SOC 2 criteria file TSC-2017.yml was intentionally not copied).
The full upstream licence text is in LICENSE-comply.txt in this folder.
The Harbor & Pine company pack built on these templates is fictional.
No endorsement by StrongDM is implied.
```

(Copy upstream `LICENSE.txt` to `inputs/templates/LICENSE-comply.txt`. Check upstream AUTHORS.txt for the exact copyright holder before finalising; UNVERIFIED.)

### Proposed `inputs/nist/SOURCES.md`

```
# NIST data sources

All files below were authored by the National Institute of Standards and
Technology (NIST), a US government agency. In the United States they are not
subject to copyright (17 U.S.C. 105). NIST notes that foreign copyright may
apply to some NIST data. The OSCAL repository additionally waives copyright
worldwide under CC0 1.0. NIST asks users to acknowledge NIST as the source.
Source: National Institute of Standards and Technology, https://www.nist.gov.
NIST does not endorse this project. Content may differ from the official
publications; refer to the originals for authoritative text.

| File | Origin | Retrieved | Commit / version |
|---|---|---|---|
| NIST_SP-800-53_rev5_catalog.json | https://github.com/usnistgov/oscal-content (nist.gov/SP800-53/rev5/json) | <DATE> | <SHA> |
| NIST_SP800-171_rev3_catalog.json | https://github.com/usnistgov/oscal-content (nist.gov/SP800-171/rev3/json) | <DATE> | <SHA> |
| NIST_CSF_v2.0_catalog.json | https://github.com/usnistgov/oscal-content (nist.gov/CSF/v2.0/json) | <DATE> | <SHA> |
| csf2.xlsx (CSF 2.0 informative references) | https://csrc.nist.gov/extensions/nudp/services/json/csf/download?olirids=all | <DATE> | n/a |
| sp800-171r3-cui-overlay.xlsx | https://csrc.nist.gov/files/pubs/sp/800/171/r3/final/docs/sp800-171r3-cui-overlay.xlsx | <DATE> | n/a |

Licence of oscal-content: https://github.com/usnistgov/oscal-content/blob/main/LICENSE.md
NIST copyright statement: https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications
```

### Open items for day 1
1. Open `csf2.xlsx` and `sp800-171r3-cui-overlay.xlsx` and record real column names and relationship values (currently UNVERIFIED).
2. Confirm 800-53 catalog minor release and control counts after download.
3. Confirm 800-171 Rev 3 requirement count (97 expected) and update the plan, which says 110.
4. Confirm upstream copyright holder line for StrongDM comply (AUTHORS.txt).
