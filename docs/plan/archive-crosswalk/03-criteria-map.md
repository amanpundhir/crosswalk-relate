# 03 · Criteria-to-feature map

For each criterion, a concrete feature a judge can find in **under a minute**. This table becomes the "Requirements map" section of the final README.

## Relate and connected context (30 points)

| Feature | Relate capability | Where a judge sees it |
|---------|-------------------|-----------------------|
| Coverage per framework, with gaps | Multi-hop traversal from framework to requirement, satisfying control and evidence | `crosswalk coverage --framework 800-171`, and the browser Coverage tab |
| Crosswalk inference: "how much of 800-171 do we already meet through our 800-53 controls?" | Quantified path patterns over `EQUIVALENT_TO` edges | `crosswalk adopt 800-171`, and the browser Adopt tab |
| Expiry blast radius | Traversal from evidence to controls, requirements, frameworks and audits | `crosswalk blast --days 30`, and the browser Blast tab (path highlight) |
| Evidence reuse ranking | Aggregation across frameworks | `crosswalk reuse`, and the scorecard |
| Mapping suggestions | Vector index plus full-text index, fused with weighted reciprocal rank fusion, filtered per framework | `crosswalk suggest CTRL-012`, and the review queue |
| Human approval stays safe | Transactions: `PROPOSED` becomes `SATISFIES` in one commit, with a bookmark | `crosswalk review`, and the change log |
| Agents ask the graph | `relate serve --mcp stdio --read-only` plus `relate skill install` | README "Ask an agent" section, and the video |
| Inspectable store | Directory store, JSON codec, committed | `data/crosswalk/` on GitHub, and `relate info` |
| No-install explorer | WASM build, in-memory what-if edits | GitHub Pages link at the top of the README |

## Functionality and completeness (25 points)

| Feature | Proof |
|---------|-------|
| One command builds the whole graph from raw inputs | `crosswalk build` re-creates `data/crosswalk/` deterministically |
| Every README command works on a cold clone | The cold-start test on Windows plus Linux or macOS, in CI (06) |
| Six core questions answered | coverage, adopt, blast, reuse, suggest, owners (bus factor) |
| Works offline with no API keys | Embeddings are precomputed and shipped. If the model is missing, it falls back to full text. |
| Errors explain how to fix them | Wrap Relate's error kinds (for example "storage locked → stop the other writer or use --read-only") |

## Usefulness (20 points)

| Feature | Proof |
|---------|-------|
| A named user and a concrete scenario | The README opens with "Maya, the security lead at Harbor & Pine, has a NIST 800-171 audit in 6 weeks" |
| Measured impact | Scorecard: evidence reuse ratio, seconds per question, gaps found 30 days early |
| Auditor-ready output | `crosswalk explain <requirement>` prints the path from requirement to control to evidence, with dates, as Markdown |

## Documentation and reproducibility (15 points)

| Feature | Proof |
|---------|-------|
| The official README template, in order | Mode, "why this mode", graph model, setup, where the data lives |
| Copy-paste quick start for Windows and macOS/Linux | Three commands to a first result |
| Graph schema diagram and a query cookbook | `docs/schema.md`, `docs/queries.md` (each question with its Cypher) |
| Scorecard published | `eval/scorecard.md`, linked from the README |
| Limits and responsible use | A section for that in the README |

## Creativity (10 points)

| Feature | Why it is fresh |
|---------|-----------------|
| An official public crosswalk used as **ground truth** to grade graph-plus-hybrid retrieval | Turns a compliance graph into a measurable retrieval benchmark |
| A browser "what-if" mode: expire evidence or remove an owner, then watch coverage drop live | In-memory WASM writes that do not touch the committed store |
| Two agents writing to one graph safely (mapper agent plus evidence agent) | A visible demo of Relate's transactions |
