# Planted scenarios (Harbor & Pine, fictional)

as_of = 2026-12-02. All facts below are in `inputs/company/*.yaml`; `tests/test_pack_lint.py` asserts the ones it can without the crosswalk.
The spec's placeholder names map to real library ids as follows. The comply templates contain no control whose wording matches the spec's example labels exactly, so the nearest real statements were used.

## Assumptions that apply to S1, S2, S5

- "Covered" follows spec section 5: an adopted control has an approved `SATISFIES` to the requirement AND at least one evidence item with `expires_at > as_of` proves that control.
- S1 and S2 rely only on DIRECT approved 800-171 mappings (rows in `mappings.yaml` with a `800-171:` requirement). They do not rely on 800-53 to 800-171 inheritance.
- Inheritance cannot weaken S1 either. I rebuilt the crosswalk in a scratch script (overlay union OSCAL, plus csf2.xlsx). Within 2 hops of `800-171:03.05.03` (via IA-2(1), IA-2(2), CSF PR.AA-01, CSF PR.AA-03) no 800-53 or 800-171 node is covered by an adopted control with valid evidence. AC-2, IA-5 and 03.01.01 were deliberately kept out of valid-evidence mappings for this reason.
- Side effect for S2: the 9 broken 171 requirements still have 800-53 neighbours that other controls cover with valid evidence (for example AU-2, PE-2, SI-2). Under an inheritance-aware reading they are "inherited", not "gaps". Under the direct-coverage rule they break.

## S1 live catch

| Spec name | Concrete id |
|---|---|
| MFA-CTRL | `CTRL-REAP-6` (VPN access with multi-factor authentication; owner Dana, sole) |
| EV-044 | `EV-044`, screenshot, collected 2026-06-01, `expires_at: 2026-12-01`. It is the only evidence for CTRL-REAP-6. |
| CTRL-X | `CTRL-PWP-4` (password manager / single sign-on wording; status partial) |

- `mappings.yaml`: CTRL-REAP-6 is approved to `800-53:IA-2(1)`, `800-53:IA-2(2)`, `800-53:AC-17`, `800-53:AC-17(2)` and directly to `800-171:03.05.03` and `800-171:03.01.12`.
- `proposals.yaml` PR-005: CTRL-PWP-4 to `800-171:03.05.03`, status pending. This is the only other path to 03.05.03, and it is not approved. CTRL-PWP-4 has one approved mapping, `800-53:IA-5(6)`.
- `legacy_tracker.csv`: CTRL-REAP-6 says "Compliant ✔", last reviewed 2026-06-20.
- Expected: 03.05.03 is NOT covered at as_of. EV-044 is in all three audits' requests.

## S2 expiring before audit

| Evidence | Control (sole evidence) | Expires | Direct approved 800-171 mappings |
|---|---|---|---|
| `EV-100` | `CTRL-LMP-15` (central log aggregation) | 2026-12-18 | 03.03.01, 03.03.03, 03.03.05 |
| `EV-101` | `CTRL-SDLCP-46` (independent vulnerability assessments) | 2027-01-05 | 03.11.02, 03.12.01, 03.14.01 |
| `EV-102` | `CTRL-DP-3` (secure area, visitor log) | 2026-12-30 | 03.10.01, 03.10.02, 03.10.07 |

- These are the only 3 evidence items with `as_of < expires_at <= 2027-01-15`. Each is the only evidence of its control, and no other control has a direct mapping to those 9 requirements.
- Total broken: 9 distinct 800-171 requirements. Each of the 3 evidence items is in the `requests` of both `AUD-171` (2027-01-15) and `AUD-53` (2027-02-20). The three controls also hold 800-53 mappings (AU-6, AU-6(3), AU-12, RA-5, CA-2, PE-2 and others), so 800-53 coverage breaks in AUD-53 as well.
- Within 30 days of as_of: EV-100 and EV-102. EV-101 only falls inside the window up to the audit date.

## S3 single owner

Dana (`P-dana-okafor`) is the sole owner of exactly 6 controls and owns nothing else: `CTRL-REAP-6` (idp, admin-vpn), `CTRL-AOTP-8` (idp, hr-system), `CTRL-AOTP-11` (idp), `CTRL-PWP-1` (idp, password-manager), `CTRL-AP-8` (backups, prod-db), `CTRL-EP-8` (kms). Every one touches a system with criticality high.

## S4 rejected suggestion

| Spec name | Concrete id |
|---|---|
| C-VPN | `CTRL-AOTP-11` ("Each month, IT and HR will review accounts and permission levels for accuracy.") |
| C-VPN-REVIEW | `CTRL-AOTP-4` ("The owner of each resource reviews and approves account creation and the associated permissions."). Adopted as a new `planned` control (owner `P-maya-chen`, applies to SYS-admin-vpn and SYS-idp) with no mappings, evidence or tracker row yet. |

- Architect change 2026-11-22: CTRL-AOTP-4 is now an adopted control that is brand new (status planned, no mappings yet), so Flow B can map it; previously it was library-only. Adopted controls: 61.
- `decisions.yaml` D-001 (proposal PR-001): CTRL-AOTP-11 to `800-53:AC-17`, rejected by `P-maya-chen` on 2026-11-25, reason "AC-17 is remote access; this control is local account review".
- Deviation from the spec: the library has no control titled "Quarterly review of VPN accounts". CTRL-AOTP-4 is the closest account-review statement not already used. For the Flow B demo, treat CTRL-AOTP-4 as the "new control" and say "review of VPN accounts" in the prompt.
- Another rejection exists: D-002 (CTRL-REAP-7 to `800-53:SC-8`, rejected 2026-11-20).

## S5 inherited coverage

- 800-171 requirements directly covered at as_of: 15 (those with a direct approved mapping and valid evidence).
- Requirements covered only through 800-53 mappings plus the crosswalk, with no direct mapping: indicative count is 23 at 1 hop, for example 03.13.11 (SC-13), 03.14.02 (SI-3), 03.05.07 (IA-5(1)), 03.01.10 (AC-11), 03.11.01 (RA-3), 03.06.01 (IR-4). It rises to 55 when 2-hop paths through CSF nodes count.
- These figures come from my scratch reconstruction of the crosswalk (union of overlay and OSCAL for 800-53/171, csf2.xlsx for CSF). The oracle's output is authoritative.
- No mapping goes to a CSF id, so `adopt CSF` shows inherited coverage only.

## S6 decoy

Control `CTRL-AP-9` (incremental backups). `EV-103` expired on 2026-11-20 (collected 2026-05-20). The replacement `EV-104` was collected 2026-11-10 and expires 2027-11-10, and `EV-068` (shared backup report) is also valid. EV-103 is expired before as_of, so it is outside the S2 window, and CP-9 coverage must not be flagged.

## S7 duplicate evidence

`EV-065` ("Quarterly identity and access review package"). It proves 5 controls: `CTRL-AOTP-8`, `CTRL-AOTP-11`, `CTRL-LMP-10`, `CTRL-OSP-5`, `CTRL-PWP-1`.
- 800-53: PS-4, AC-2(3), AC-6(7), AU-2, AC-2(4), PE-2, IA-5(1) (7 requirements).
- 800-171, direct: 03.09.02 (AOTP-8) and 03.01.05 (AOTP-11).
- CSF: reached through the crosswalk only (no CSF mappings exist). Per my crosswalk reconstruction, EV-065 reaches 20 distinct requirements across all three frameworks, with the next best item at about 14.
- Requested by all three audits. Valid until 2027-04-03.

## S8 unowned control

`CTRL-MCP-13` (use only cloud storage providers that can demonstrate security accreditation): `owners: []`, status implemented, with valid evidence. `legacy_tracker.csv` still lists "Marcus Webb" as owner (a departed person who is not in `people.yaml`). `CTRL-ASP-22` also lists him in the legacy tracker but has a current owner in `controls.yaml`.

## Other deliberately stale legacy rows

"Compliant ✔" in the legacy tracker but not valid: CTRL-REAP-6 (S1), BCP-4, ASP-12, REAP-3 (sole evidence expired), SCP-8 (partial). Also stale: AP-8 says "In progress" though it is implemented with valid evidence.

## Architect corrections (2026-11-22, after the oracle run)

The oracle (`eval/oracle.py`, `eval/ground_truth.json`) is the source of truth. Where this file disagrees, the oracle wins:

- **S2:** of the 9 800-171 requirements that lose direct coverage before 2027-01-15, **5 are still inherited** at 1 hop. **4 are fully broken**: 03.03.05, 03.10.02, 03.11.02 and 03.12.01. In the 30-day window the count is 6 (EV-100 and EV-102). The demo uses this split: "broken but still met via X" vs. "fully broken".
- **S7:** the reuse ranking key is (direct requirements, then frameworks reached, then 1-hop reach), so EV-065 ranks first. EV-069 has the larger 1-hop reach (28 vs. 20), but fewer direct requirements.
- **S3:** Dana is the sole owner of 6 controls, all on high-criticality systems, but she is **not** the largest sole owner. Hugo has 9 and Omar has 7. The demo asks "What if Dana leaves?", not "Who is the single point of failure?".
