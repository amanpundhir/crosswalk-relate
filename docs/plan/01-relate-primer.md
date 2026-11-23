# 01 · Relate primer (what we are building on)

Checked against the relatedb.ai docs and the GitHub repo on 2026-11-22. **Version 1.2.0**, Apache-2.0.

## What Relate is

Relate is an **embedded property-graph database** written in Rust that speaks **Cypher 25**. It runs as a library inside your app or as a single CLI binary, with no server and no signup. Think "SQLite, but a graph".

## Ways to run it

| Surface | Install | We use it for |
|---------|---------|---------------|
| CLI (Windows) | `irm https://relatedb.ai/install.ps1 \| iex` | Judges' quick checks, `relate serve` |
| CLI (macOS/Linux) | `curl -sSfL https://relatedb.ai/install.sh \| bash` | Same |
| Python | `pip install relate-db` (`import relate`) | Data ingest, embeddings, evaluation, our CLI |
| Browser (WASM) | `npm install @relate/relate-wasm` | The no-install explorer on GitHub Pages |
| Agent skill | `relate skill install --agent claude-code` | Lets coding agents discover and use the graph |
| MCP server | `relate serve --mcp stdio --database <path> --read-only` | Agent Q&A over the graph |

Other bindings (Node.js, Rust, Java, Go, .NET, Swift, C) exist but we do not need them.

## Storage modes (the README must name and justify one)

| Mode | How it is chosen | Behaviour |
|------|------------------|-----------|
| In memory | `:memory:` (the default) | Lost on exit. Judges cannot inspect it. |
| Single file | A path ending in `.rl` | One file. A writer holds a lock, so read-only opens are refused while it is writing. |
| Directory | Any other path | A folder. The codec is Parquet by default or **JSON** (`--snapshot-format json`), which makes it diffable. Read-only readers can run next to a writer, and `--read-only=live` follows the writer's commits. |

**Our choice: a directory store with the JSON codec.** The main reason is that Relate's MCP server can run `--read-only=live` beside the writer, so several agents can read while proposals and decisions are being written. The store is also readable and diffable on GitHub. Full reasons are in 04.

Useful commands: `relate info --database <path>` shows metadata, and `relate clone <src> <dst> [--to-snapshot-format json]` copies a store between layouts.

## Features we will use

| Feature | Stable? | Our use (Crosswalk) |
|---------|---------|---------|
| Cypher reads and writes, `CALL` subqueries, quantified path patterns | Stable | Coverage, adopt, blast radius, reuse, owner risk, and the paths behind each claim |
| Directory store, JSON codec, `--read-only=live` | Stable | Committed store. The MCP reader follows the writer's commits |
| Transactions (Python `autocommit=False`, `commit()` returns a bookmark, retryable conflicts) | Stable | Human approval decisions, and concurrent agents writing without clobbering |
| Vector index with `SEARCH ... VECTOR INDEX` and a `WITH [framework]` filter | Stable | Mapping candidates per framework |
| Full-text index (BM25) with `SEARCH ... FULLTEXT INDEX` | Stable | Keyword half of hybrid search |
| Hybrid search through manual WRRF (`CALL { ... UNION ALL ... }`) | Stable | The main candidate engine |
| `COMBINE ... USING WRRF` | **Preview** | Optional. Shown only as "also works with" |
| MCP tools `get_schema`, `read_cypher` (read-only server) | Stable | Free exploration by agents. Writes go only through our narrow `crosswalk-mcp` propose tools |
| `relate skill install --agent claude-code` | Stable | Lets Claude Code discover and use Relate |
| CLI `--mode envelope` (JSON with a `truncated` field) | Stable | Agent-ready output in the README examples |
| WASM `RelateDb`, `execute`, `executeScript` | Stable | Browser explorer, agent log view and in-memory what-if |
| `EXPLAIN` / `PROFILE` | Stable | Latency KPI and the query docs |

## Limits that shape the design

- **Vector search is exact (brute force).** HNSW settings are stored but not used. That is fine at our size (about 1.5k requirement nodes), and the README will say so.
- **Vector dimensions** can be 1 to 4096. We plan 384, from a small local embedding model, precomputed and shipped in the store.
- **Full-text search** has no phrase matching and no stemming by default. That is why hybrid search beats full text alone.
- **Vector `SEARCH`** requires a `LIMIT`, allows no `SKIP`, and permits one `SEARCH` per `MATCH`. Its `WHERE` can only use properties listed in the index's `WITH`.
- **The WASM build** cannot open `.rl` or directory stores and has no transactions. The browser therefore loads a Cypher script that we export from the store, and the browser copy is in memory only.
- **File stores are single-writer** across processes. Run the MCP server `--read-only`, and do writes through our CLI.
- The whole graph is held in memory. That is not a problem at our size.
- **Telemetry is on by default.** The README will show `relate telemetry off` or `DO_NOT_TRACK=1`.
- Windows has no `relate upgrade` (rerun the installer) and no ARM64 native build.

## Verified on our machine (day 1, Windows 11, Relate 1.2.0)

Full log: [docs/day1/env-setup.md](../day1/env-setup.md).

- `pip install relate-db` gives the Python package only, **not** the CLI. The CLI is the official release asset `relate-windows-amd64.exe` (SHA-256 checked against `SHA256SUMS`), placed in `.venv\Scripts\relate.exe`, so it works only when the venv is active.
- **Readers beside a writer work on a directory store.** `--read-only` and `--read-only=live` both open while a Python writer holds the store, and a second writer is refused (exit 5, "storage locked").
- **Use `--read-only=live` for the MCP server.** A plain `--read-only` connection that stays open is a frozen snapshot and misses later commits. A long-running `relate serve --mcp stdio --read-only=live` saw new commits without a restart.
- The MCP tools are `get_schema` and `read_cypher`, and **`read_cypher` takes `statement`** (not `query`).
- A `.rl` file refuses read-only opens while a writer holds it, which confirms the directory-store choice.
- **Full-text `SEARCH` also needs `LIMIT`**, not only vector search. The vector `WITH [prop]` filter works.
- Python transactions: `commit()` returns a string bookmark such as `'relate:1'`, and `rollback()` works.
- **The JSON store's `graph.json` is a single line**, rewritten only at a checkpoint (on clean close). Until then, commits live in `wal/*.log`. Lock files (`.cypherlite.lock`, `.cypherlite.writer`) sit inside the store and are gitignored. Note that the 1.2.0 binary still uses `.cypherlite` names.
- Telemetry: `DO_NOT_TRACK=1` disables it per session. We did not run `relate telemetry off`, because that saves a setting outside the project.

## Docs to read during the build (not yet read)

CLI flags and agent mode (exact row cap), Bolt and the HTTP API, transactions and concurrency, `relate pull`/`push` for Neo4j, the skill file layout, the full limitations page, and the differences from Neo4j's Cypher.
