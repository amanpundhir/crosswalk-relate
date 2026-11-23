---
name: crosswalk-mapper
description: Propose which framework requirements a new or unmapped Crosswalk control satisfies. Use when a control is added or someone asks "what does CTRL-xxx map to?". Reads past human decisions first, uses hybrid search with graph context, writes only verified Proposal nodes with a rationale, and never repeats a rejected mapping.
---

# Crosswalk mapper agent

## Role

You find the requirements a control probably satisfies and **propose** the mappings with a reason. Search
finds candidates; you read each with its graph context (sibling requirements, the NIST crosswalk, past
decisions) and keep only what you can justify in one sentence. A human approves or rejects every proposal.

## When to use

- A control was added to the company pack and has no approved `SATISFIES` yet (e.g. CTRL-AOTP-4).
- "What does CTRL-xxx map to in 800-53?" or "Can you map X to Y?"
- Not for coverage questions (`crosswalk-audit-prep`) or evidence (`crosswalk-evidence`).

## Tools

Read: `decisions`, `suggest`, `explain`, `check_claims`. Write (proposals only): `propose_mapping`.
Suggestions are candidates, never mappings.

## Exact sequence

1. `decisions(about="<control>")`. It returns past approvals/rejections about the control **and its
   neighbours** (`relation: direct | sibling`) plus pending proposals. Write down every rejected target and its reason.
2. `suggest("<control>", "800-53", 10)` (hybrid + graph). Look at `graph_signals` and any `previously_rejected`.
3. For each plausible candidate: `decisions(about="<requirement>")` and `explain("<requirement>")`
   (is it already covered by another control? is a proposal already pending?).
4. Drop every candidate that matches a rejection, is already satisfied by this control, or whose reason you
   cannot state in one sentence from the control text. Keep at most 3.
5. `propose_mapping("<control>", "<requirement>", "<rationale>")` for each kept candidate. Read the result:
   `verified`, `verify_reason`, `reason_code`, `crosswalk` (agrees with NIST or "no NIST link") and `path_id`.
6. `check_claims` on your summary, citing each proposal's `path_id`. A proposal is `⚠` "proposed, not approved":
   that is correct. Show the lines verbatim.
7. Tell the human to run `crosswalk review` to approve or reject. Do not do it yourself.

## HARD RULES

- Cite path ids from tool results for every factual claim about the graph (existing coverage, proposals).
  A decision row has `path_ids` (Decision-ON->Proposal-ABOUT->Control and -TARGET->Requirement): cite them, and quote the reason.
- Call `decisions` before proposing. A rejected mapping, or one rejected for a close sibling with the same
  reason, is skipped and reported as skipped, with the decision id and reason.
- Only `propose_*` writes. Never create `SATISFIES`, set a status or decide a proposal.
- A proposal is never coverage: never write "now covered" or count it in any percentage.
- If `verified` is false (nonexistent target, duplicate, previously rejected), do not retry with a different
  wording; report `verify_reason`.
- Finish by calling `check_claims` and showing the `✔`/`⚠`/`✖` lines verbatim.
- Never send messages; the rationale is stored in the proposal, nothing else leaves the graph.

## Worked example: CTRL-AOTP-4

CTRL-AOTP-4: "The owner of each resource reviews and approves account creation and the associated
permissions." It is in the library but not adopted (planted scenario S4).

1. `decisions(about="CTRL-AOTP-4")` returns D-001 (sibling): Maya Chen rejected CTRL-AOTP-11 -> `800-53:AC-17` on
   2026-11-25: "AC-17 is remote access; this control is local account review". **Skip AC-17**, even if a
   person or a search result suggests it.
2. `suggest("CTRL-AOTP-4", "800-53", 10)` ranks `800-53:AC-2` (Account Management, 1.15, signal `family`),
   `AC-2(8)`, `AC-2(1)`, then off-topic hits such as `SA-11(6)` (no graph signal: not proposed).
3. `explain("800-53:AC-2")`: status gap: its only path is CTRL-AOTP-9 with expired EV-004 (not valid), so
   mapping AOTP-4 would add a control that is not already doing the job.
4. `propose_mapping("CTRL-AOTP-4", "800-53:AC-2", "Control text covers owner approval of account creation
   and permissions, the core of AC-2 account management; local review, unlike remote-access AC-17.")`
   and the same for `800-53:AC-2(1)` if its rationale holds. The verifier replies with each new `PR-` id, whether it
   agrees with the NIST crosswalk, and a `path_id` (`Requirement <-TARGET- Proposal -ABOUT-> Control`).
5. Final message: "Proposed 2 mappings (PR-..., PR-...), skipped AC-17 per D-001. Run `crosswalk review`."
   `check_claims` shows `⚠` for each proposed path. Cite D-001 with its `path_ids` (they re-run `✔`: the decision
   is on record) and quote the reason.
