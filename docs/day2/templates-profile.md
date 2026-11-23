# Templates profile (StrongDM comply, commit aab484948d71417e35a079c0395bcf42e16a8dd9)

Profiled 2026-11-22 from `inputs/templates/comply/` (unmodified copies). Scripts: `.scratch/templates/{profile,split,vague,gen}.py`.

## Inventory
- policies: 27 policy files plus README.md. procedures: 4 files plus README.md. narratives: 5 files plus README.md.
- Nothing copied from `example/standards/` (TSC-2017.yml excluded).
- Copyright holder: none stated upstream (see `inputs/templates/NOTICE.md`).

## Per-policy table
"a." = top-level items, "i." = second-level roman items, "1." = third-level digit items. Controls = count under the split rule below. Every policy has exactly the YAML keys `name, acronym, satisfies, majorRevisions`.

| File | Name | Acronym | a. | i. | 1. | Controls |
|---|---|---|---|---|---|---|
| access.md | Access Onboarding and Termination Policy | AOTP | 8 | 11 | 0 | 11 |
| application.md | Application Security Policy | ASP | 16 | 34 | 0 | 36 |
| availability.md | Availability Policy | AP | 14 | 14 | 0 | 20 |
| change.md | System Change Policy | SCP | 9 | 8 | 0 | 12 |
| classification.md | Data Classification Policy | DCP | 20 | 27 | 54 | 15 |
| conduct.md | Code of Conduct Policy | COCP | 16 | 16 | 7 | 15 |
| confidentiality.md | Confidentiality Policy | CP | 10 | 23 | 6 | 15 |
| continuity.md | Business Continuity Policy | BCP | 8 | 16 | 15 | 9 |
| cyber.md | Cyber Risk Assessment Policy | CRP | 16 | 11 | 0 | 18 |
| datacenter.md | Datacenter Policy | DP | 10 | 12 | 0 | 15 |
| development.md | Software Development Lifecycle Policy | SDLCP | 15 | 58 | 15 | 59 |
| disaster.md | Disaster Recovery Policy | DRP | 15 | 21 | 4 | 20 |
| encryption.md | Encryption Policy | EP | 7 | 7 | 0 | 8 |
| incident.md | Security Incident Response Policy | SIRP | 26 | 18 | 0 | 34 |
| information.md | Information Security Policy | ISP | 18 | 19 | 1 | 14 |
| log.md | Log Management Policy | LMP | 10 | 16 | 0 | 18 |
| media.md | Removable Media and Cloud Storage Policy | MCP | 18 | 25 | 18 | 29 |
| office.md | Office Security Policy | OSP | 8 | 8 | 24 | 8 |
| password.md | Password Policy | PWP | 5 | 7 | 0 | 7 |
| policy.md | Policy Training Policy | PTP | 3 | 6 | 0 | 6 |
| privacy.md | Privacy Management Policy | PMP | 0 | 0 | 0 | 0 |
| processing.md | Processing Integrity Policy | PIP | 0 | 0 | 0 | 0 |
| remote.md | Remote Access Policy | REAP | 6 | 15 | 0 | 12 |
| retention.md | Data Retention Policy | RP | 9 | 13 | 4 | 14 |
| risk.md | Risk Assessment Policy | RIAP | 8 | 14 | 7 | 14 |
| vendor.md | Vendor Management Policy | VMP | 13 | 2 | 0 | 8 |
| workstation.md | Workstation Policy | WP | 6 | 13 | 0 | 13 |
| **Total** | | | 294 | 414 | | **430** |

Notes: all 27 acronyms are unique. privacy.md (PMP) and processing.md (PIP) are stubs ("# Coming Soon", only a `satisfies` list) with 0 statements. Procedures use keys `id, name, (cron)` and have 5 to 11 `- [ ]` checkbox bullets each (steps, not statements). Narratives use `name, acronym, (satisfies), majorRevisions` and are prose plus bullets (control.md 33 bullets, organizational.md 16, security.md 9, products.md and system.md 0); they are not control statements.

## Markdown patterns
- Front matter: YAML terminated by a line `---`, but there is NO opening `---` (a file starts directly with `name:`). Split on the first `\n---\n`.
- Sections: `# Purpose and Scope`, `# Background`, `# References`, `# Policy`, plus policy-specific H1s (for example `# Procedure For Executing Incident Response`) and sometimes `## ` subheads and "Appendix A:" lines. Normative text is mostly under `# Policy`.
- Statements: markdown ordered lists in which every sibling repeats the same marker (numbering is generated at render time). Level 1 is `a. text` (column 0; conduct.md indents 2 spaces). Level 2 is `i. text` indented 4 spaces. Level 3 is `1. text` indented 8 spaces. A heading-only level-1 item is italic: `a. *Rotation requirements*`, with the real statements as level-2 children. Some level-1 items are full sentences with no children. Items have trailing spaces and blank lines between them; `\pagebreak` lines occur in some files.
- Placeholders: only `{{.Name}}` (39 occurrences, all in narratives; none in policies or procedures). Policies use generic words ("the organization", "the company") and unresolved roles (CIO, ISM, Engineering Lead). "(reference (a))" and "Table 3" are plain text.
- Procedures and narratives use `- [ ]` checkboxes or `-` bullets.

## Sample statements (verbatim)
1. PWP: "All system-level passwords should be rotated on at least a quarterly basis. All user-level passwords should be rotated at least every six months."
2. SCP: "All change requests must be documented."
3. AOTP: "IT terminates access within five business days from receipt of notification."
4. CP: "View confidential information only on secure devices"
5. ASP: "The organization must ensure that all applications it develops and/or acquires are securely configured and managed."

## Proposed deterministic split rule
1. Parse each `policies/*.md` except README.md; read `acronym` from the front matter.
2. Walk lines in order tracking the current H1. Skip sections whose H1 matches `/purpose|scope|background|references|appendix|overview|coming soon/i`.
3. A list item is a line matching `^\s*([a-z]|[ivx]+|\d+)\.\s+`; level 1 for `a`, level 2 for roman, level 3 for digits. Append following non-blank, non-list, non-`\` lines to the current item.
4. A control is every level-2 item, with its level-3 children folded in (joined with " | "), plus every level-1 item that has no level-2 children (a standalone statement). The parent level-1 text is kept as `context`.
5. Level-1 items that have children are headings only and are not controls.
6. Id = `CTRL-<ACRONYM>-<n>`, n = 1-based order of the control within its file after steps 2 to 5, unpadded (for example CTRL-PWP-3). Also store `text_hash = sha1(normalised text)[:8]`. Because the upstream commit is pinned, ids are stable; the hash allows remapping if the pin ever moves.
7. Procedures and narratives are not split into controls (supporting documents only).

## Estimated control count
430 controls from 25 non-stub policies (PMP and PIP give 0). Range 6 to 59 per policy (SDLCP 59, ASP 36, SIRP 34, MCP 29), median about 14. Alternatives: top-level `a.` only gives 294 but mixes headings with statements; also splitting level 3 gives roughly 600 to 650.

## Vague or non-control statements to flag
About 60 of 430 (roughly 15%) are weak under a simple heuristic (fewer than 6 words, cross-reference only, or a dangling stem); more are borderline.
- Bare labels and fragments: SDLCP "Requirements Analysis", "Architecture and Design", "Testing", "Decommission" (phase headings written as list items); DP "Smoking, eating, or drinking." and "Use of portable heating devices." (continuations of a stem that is lost when split; check context).
- Cross-reference only: AP "Recovery time and data loss limits are defined in Table 3."; several ASP items that only point to other policies ("... is defined in the Disaster Recovery Policy").
- Descriptions or definitions, not requirements: ASP "Quick - consists of an automated scan ..."; DCP items describing classification inputs; SCP step labels such as "*Planning*: plan the change ...".
- Process narration without a modal verb (AOTP "HR emails IT to inform them of a new hire and their role."). Usable, but phrased as a step, not a requirement.
- Soft language ("should", "where possible", "may") is common, so NIST mapping will be loose.
- Wording dates from 2018 and uses unresolved roles; curly quotes may show as a replacement character if read with the wrong encoding (read as UTF-8).
- Recommendation: add a boolean `vague` flag on the Control node instead of dropping these, and exclude flagged ones from any ground-truth evaluation.
