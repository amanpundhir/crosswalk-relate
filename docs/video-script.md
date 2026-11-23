# Demo video script (target 1:50, hard limit 2:00)

A 1920×1080, 30 fps video. Real app footage and faithful recreations carry the story, with motion graphics between them. It has a text-to-speech voice-over, burned-in captions (many judges watch muted) and quiet music. Nothing is recorded by hand: the kit already holds everything. Every number below comes from the committed store (demo date 2026-12-02) and [eval/agent-runs/results-run2.md](../eval/agent-runs/results-run2.md). Do not round or change them.

The video is built with HyperFrames from the local kit in `video-kit/` (gitignored). The prompt for the video agent is `video-kit/PROMPT.md`.

## Scenes

About 250 words of voice-over in 110 seconds, which is a calm pace.

| # | Time | On screen | Voice-over |
|---|---|---|---|
| 1 | 0:00–0:09 | **Hook.** A spreadsheet row animates in: `MFA · CTRL-REAP-6 · Compliant ✔` (green). A chat bubble from a generic "AI agent" types the recorded answer: "Yes. 800-171:03.05.03 (Multi-Factor Authentication) is fully covered by CTRL-REAP-6 and CTRL-PWP-4." | "Your compliance spreadsheet says multi-factor authentication is compliant. Ask an AI, and it agrees." |
| 2 | 0:09–0:17 | **Twist.** The evidence card `EV-044` slides in and gets a red **EXPIRED 2026-12-01** stamp. The green tick turns red. Cut to the title: Crosswalk mark + "Crosswalk: audit-prep AI that answers with receipts" + small "Built on Relate". | "But the evidence behind it expired yesterday. Nobody noticed. This is Crosswalk: an audit-prep agent that answers with receipts." |
| 3 | 0:17–0:33 | **The graph.** An animated graph builds up: three framework clusters (800-53, 800-171, CSF 2.0) joined by crosswalk lines, then controls, evidence and people attach. Counters: **1,217 requirements · 1,204 crosswalk links · 1,971 nodes**. Then one path highlights: `03.05.03 ← CTRL-REAP-6 ← EV-044`, labelled "a receipt". Finish on still 03 (the receipt in the app). | "Crosswalk puts three NIST frameworks, NIST's official crosswalk between them, and a company's controls, evidence and owners into one Relate graph. It's just a folder in the repo. Every answer the agent gives cites a path through that graph: requirement, control, evidence." |
| 4 | 0:33–0:55 | **The live catch.** A recreated terminal types `crosswalk demo live-catch`, and the real output (`assets/text/live-catch-output.txt`) prints line by line, with callouts on ✖ EV-044 expired, ⚠ PR-005 proposed and `0/2 claims verified`. Then the real explorer footage `clip-live-catch-explorer` from 0 to 6.8 s, ending on the corrected answer. | "Here's the catch, live. Maya asks: is MFA covered for the 800-171 audit? The agent says yes. The claim checker re-runs both paths against the graph in milliseconds. EV-044 expired on December first. The second mapping was only ever proposed. Zero of two claims hold. The corrected answer: not covered. Renew EV-044. The request is already drafted." |
| 5 | 0:55–1:12 | **Inside your agent.** A recreated agent chat window (generic, not a copy of any product) plays the recorded GQ-05 run word for word (`assets/text/agent-mfa-recorded.md`): question, two tool calls, both claims with their receipts, answer. Small label: "Recreated from a recorded run". Then "Approve PR-005 for me." appears and the toolbox card (`assets/text/agent-toolbox.md`) shows no approve tool. End on the real footage `clip-live-catch-explorer` 9.0–11.9 s: "Agents can only propose", AC-17 rejected by Maya. | "It works inside your own agent. One command connects Claude Code, or any MCP client, to the graph. Ask it to approve a pending mapping, and it can't: agents can only propose. A person decides, and every decision is remembered." |
| 6 | 1:12–1:27 | **What-if.** The real footage `clip-whatif-ev100` (12 s; trim or speed up the waits), with an animated cursor on the three clicks. Zoom on the totals: **Covered 15 → 12, Gaps 59 → 60**. | "Plan ahead, too. Expire one piece of evidence and watch it ripple: three requirements lose their proof. Covered drops from fifteen to twelve; gaps rise to sixty." |
| 7 | 1:27–1:42 | **The result.** Two bars race: Spreadsheet **9/20 (45%)** against Crosswalk **19/20 (95%)**. Then three stat tiles: **0 of 14 traps**, **0 wrong claims shown**, **109/109 claims with a receipt**. Small print: "One model, 20 questions, fictional company. Transcripts in the repo." | "Does it matter? Same model, same twenty audit questions. Reading the spreadsheet: nine right. With Crosswalk and Relate: nineteen right, zero of fourteen traps, and zero wrong claims shown. Every claim backed by a receipt." |
| 8 | 1:42–1:50 | **Close.** Crosswalk mark, "Answers with receipts", then three lines: `github.com/amanpundhir/crosswalk-relate`, `amanpundhir.github.io/crosswalk-relate`, "Free · runs locally · Apache-2.0". Small "Harbor & Pine is a fictional company." | "Free, local and open source. Try the explorer in your browser, with no install. Crosswalk: answers with receipts." |

## Footage and voice (all in `video-kit/`, nothing to record)

| Source | Used in | What it is |
|---|---|---|
| `assets/clips/clip-whatif-ev100/` | scene 6 | real explorer recording (12 s frame sequence; timings and click cues in `assets/clips/README.md`) |
| `assets/clips/clip-live-catch-explorer/` | scenes 4, 5 | real explorer recording (11.9 s): the live catch, then "Proposals and decisions" |
| `assets/stills/` | anywhere | 11 real 1920×1080 screenshots, plus the result chart |
| `assets/text/live-catch-output.txt` | scene 4 | the real terminal output of `crosswalk demo live-catch`, for the recreated terminal |
| `assets/text/agent-mfa-recorded.md` | scene 5 | the recorded agent run (GQ-05), verbatim, for the recreated chat |
| `assets/text/agent-toolbox.md` | scene 5 | the agent's real tool list (no approve, send or delete) |

Recreated scenes use real text only, and carry a small "Recreated from a recorded run" or "Real output" label. The voice-over is generated with text-to-speech from the text above: a calm, clear English voice, one file per scene.

## Before uploading

- [ ] Length is 2:00 or less. Every number on screen matches this script.
- [ ] Captions are readable on a phone, and no text sits outside the title-safe area.
- [ ] No real names, emails or company data on screen. "Fictional" is shown once.
- [ ] No Neo4j logo, and nothing suggests Neo4j endorses the project ("Built on Relate" is fine).
- [ ] Music and the text-to-speech voice are free to use, and their sources are noted in `CREDITS.md`.
- [ ] Uploaded to YouTube as **unlisted**. Check that it plays in a logged-out browser window.
- [ ] Paste the link into the README placeholder `<!-- VIDEO_LINK -->`.
