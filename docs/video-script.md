# Demo video script (target 1:50, hard limit 2:00)

Record at 1920×1080 with a terminal font of 16pt or larger. Run `$env:DO_NOT_TRACK="1"` first. Every number below comes from the committed store (`as_of` 2026-12-02) and `eval/scorecard.md`. Re-run each command before recording and read out what it actually prints.

| Time | Beat | On screen | Voice-over (short) |
|---|---|---|---|
| 0:00–0:10 | Problem | Title card, then `legacy_tracker.csv` open with a column of "Compliant ✔" | "Three NIST frameworks, hundreds of requirements, and a spreadsheet that says everything is fine. An AI reading that spreadsheet will say the same." |
| 0:10–0:18 | Theme | Browser explorer landing page | "Crosswalk is an audit-prep agent that answers with receipts. Every claim is a path in a Relate graph, and the graph checks it." |
| 0:18–0:50 | **The live catch** | `crosswalk demo live-catch` in the terminal | "Maya asks: is MFA covered for the 800-171 audit? The agent says yes. Then the claim checker re-runs both paths: evidence EV-044 expired yesterday, and the second mapping was only ever proposed. Zero of two claims hold. The corrected answer: not covered, renew EV-044, and the request is drafted." Then cut to the browser **Agent log** tab and click "Show broken path on graph". |
| 0:50–1:08 | Mapper with memory | `crosswalk decisions`, then `crosswalk suggest CTRL-AOTP-4 --k 5`, then `crosswalk propose-map CTRL-AOTP-4 800-53:AC-17 …` showing the ✖ "previously rejected" (Maya, 2026-11-25), then `crosswalk review` approving AC-2 | "A new control. The mapper reads past decisions first. Maya rejected AC-17 for a sibling control last week, so the verifier blocks it. AC-2 is approved in one transaction, and coverage moves." |
| 1:08–1:20 | What breaks, plus two agents | `crosswalk blast --audit AUD-171`: "9 lose direct coverage (4 fully broken, 5 still met via another framework)". Then `python -m crosswalk.demo_concurrency --mode server`: write-write conflict, retry, both land. | "Three evidence items expire before the audit. Two agents write at once through Relate's server: one conflict, one retry, nothing lost." |
| 1:20–1:40 | Evidence | `eval/scorecard.md` headline plus the three-column agent table | "Same model, same 20 questions. Reading the spreadsheet: 9 right. Using the graph with the checker: 19 right, and zero wrong claims shown. A rejected mapping is never proposed again." |
| 1:40–1:50 | Close | `crosswalk agent setup --yes` (self-test ✔), then `data/crosswalk/` in the file tree | "One command wires it into your agent. The whole graph is a folder in the repo. Crosswalk: answers with receipts." |

## Recording checklist

- [ ] Reset the demo state first: rebuild with `crosswalk build`, so the proposals from earlier test runs are gone and `review` shows the expected queue.
- [ ] Run the mapper beat on a temp copy (`--store`), or rebuild after recording.
- [ ] No real names, emails or company data on screen. The company is fictional and labelled as such.
- [ ] Upload as unlisted, then check it plays in a logged-out browser window.
- [ ] Paste the link into the README placeholder `<!-- VIDEO_LINK -->`.
