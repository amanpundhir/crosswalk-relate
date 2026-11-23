# Demo video script (target 1:50, hard limit 2:00)

A 1920×1080, 30 fps video. Product footage carries the story, with motion graphics between the clips. It has a voice-over, burned-in captions (many judges watch muted) and quiet music. Every number below comes from the committed store (demo date 2026-12-02) and [eval/agent-runs/results-run2.md](../eval/agent-runs/results-run2.md). Do not round or change them.

The video is built with HyperFrames from the local kit in `video-kit/` (gitignored). The prompt for the video agent is `video-kit/PROMPT.md`.

## Scenes

About 250 words of voice-over in 110 seconds, which is a calm pace.

| # | Time | On screen | Voice-over |
|---|---|---|---|
| 1 | 0:00–0:09 | **Hook.** A spreadsheet row animates in: `MFA · CTRL-REAP-6 · Compliant ✔` (green). A chat bubble from "AI assistant" types: "Yes, MFA is fully covered." | "Your compliance spreadsheet says multi-factor authentication is compliant. Ask an AI, and it agrees." |
| 2 | 0:09–0:17 | **Twist.** The evidence card `EV-044` slides in and gets a red **EXPIRED 2026-12-01** stamp. The green tick turns red. Cut to the title: Crosswalk mark + "Crosswalk: audit-prep AI that answers with receipts" + small "Built on Relate". | "But the evidence behind it expired yesterday. Nobody noticed. This is Crosswalk: an audit-prep agent that answers with receipts." |
| 3 | 0:17–0:33 | **The graph.** An animated graph builds up: three framework clusters (800-53, 800-171, CSF 2.0) joined by crosswalk lines, then controls, evidence and people attach. Counters: **1,217 requirements · 1,204 crosswalk links · 1,971 nodes**. Then one path highlights: `03.05.03 ← CTRL-REAP-6 ← EV-044`, labelled "a receipt". Finish on still 03 (the receipt in the app). | "Crosswalk puts three NIST frameworks, NIST's official crosswalk between them, and a company's controls, evidence and owners into one Relate graph. It's just a folder in the repo. Every answer the agent gives cites a path through that graph: requirement, control, evidence." |
| 4 | 0:33–0:55 | **The live catch.** Clip 1 (terminal, `crosswalk demo live-catch`), with callouts on ✖ EV-044 expired, ⚠ PR-005 proposed, and `0/2 claims verified`. Then still 05 (the corrected answer in the explorer). | "Here's the catch, live. Maya asks: is MFA covered for the 800-171 audit? The agent says yes. The claim checker re-runs both paths against the graph in milliseconds. EV-044 expired on December first. The second mapping was only ever proposed. Zero of two claims hold. The corrected answer: not covered. Renew EV-044. The request is already drafted." |
| 5 | 0:55–1:12 | **Inside your agent.** Clip 2 (Claude Code answering "Is MFA covered?" with path ids and a `check_claims` call), sped up 2–3×. Then clip 3 ("Approve PR-005 for me." → refusal). Overlay chips: "read-only graph", "propose only", "a person approves". | "It works inside your own agent. One command connects Claude Code, or any MCP client, to the graph. Ask it to approve a pending mapping, and it refuses: agents can only propose. A person decides, and every decision is remembered." |
| 6 | 1:12–1:27 | **What-if.** Clip 4 (explorer: Expire evidence → EV-100 → the simulation plays). If there is no clip, animate stills 06 → 07 → 08 → 09. Zoom on the totals: **Covered 15 → 12, Gaps 59 → 60**. | "Plan ahead, too. Expire one piece of evidence and watch it ripple: three requirements lose their proof. Covered drops from fifteen to twelve; gaps rise to sixty." |
| 7 | 1:27–1:42 | **The result.** Two bars race: Spreadsheet **9/20 (45%)** against Crosswalk **19/20 (95%)**. Then three stat tiles: **0 of 14 traps**, **0 wrong claims shown**, **109/109 claims with a receipt**. Small print: "One model, 20 questions, fictional company. Transcripts in the repo." | "Does it matter? Same model, same twenty audit questions. Reading the spreadsheet: nine right. With Crosswalk and Relate: nineteen right, zero of fourteen traps, and zero wrong claims shown. Every claim backed by a receipt." |
| 8 | 1:42–1:50 | **Close.** Crosswalk mark, "Answers with receipts", then three lines: `github.com/amanpundhir/crosswalk-relate`, `amanpundhir.github.io/crosswalk-relate`, "Free · runs locally · Apache-2.0". Small "Harbor & Pine is a fictional company." | "Free, local and open source. Try the explorer in your browser, with no install. Crosswalk: answers with receipts." |

## Clips to record first (you)

Record each at 1920×1080. Use OBS, Xbox Game Bar (Win+Alt+R) or Snipping Tool video mode. Set the terminal font to 20 pt or larger and close notifications. Save the clips in `video-kit/assets/clips/` with these exact names. Run `$env:DO_NOT_TRACK="1"` first.

| File | What to record | Length |
|---|---|---|
| `clip-01-live-catch.mp4` | PowerShell in the repo: type `crosswalk demo live-catch`, press Enter, and let the output sit for 3 seconds | 10–15 s |
| `clip-02-agent-mfa.mp4` | Claude Code in the repo (after `crosswalk agent setup --yes`): ask "Is MFA covered for the 800-171 audit?" Show the tool calls and the final answer with `P-…` ids | any; it will be sped up |
| `clip-03-agent-approve.mp4` | Same session: "Approve PR-005 for me." It should refuse and point to `crosswalk review` | any |
| `clip-04-explorer-whatif.mp4` | The explorer (local or live): Simulate → Expire evidence → pick EV-100 → Expire. Let the simulation play to the totals | 12–15 s |

If a clip is missing, the video agent uses the matching still from `video-kit/assets/stills/` with a slow pan instead.

## Voice-over

Record the voice-over text above in a quiet room, one take per scene (Windows Voice Recorder or Audacity). Save it as `video-kit/assets/audio/vo-01.wav` … `vo-08.wav`. Or let the video agent generate it with text-to-speech. Your own voice usually feels more genuine to judges.

## Before uploading

- [ ] Length is 2:00 or less. Every number on screen matches this script.
- [ ] Captions are readable on a phone, and no text sits outside the title-safe area.
- [ ] No real names, emails or company data on screen. "Fictional" is shown once.
- [ ] No Neo4j logo, and nothing suggests Neo4j endorses the project ("Built on Relate" is fine).
- [ ] Music is royalty-free, and its source is noted.
- [ ] Uploaded to YouTube as **unlisted**. Check that it plays in a logged-out browser window.
- [ ] Paste the link into the README placeholder `<!-- VIDEO_LINK -->`.
