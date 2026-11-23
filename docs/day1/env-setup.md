# Day 1 environment setup and checks (2026-11-22)

## What is installed, and where
All inside the project folder. Nothing global, no user PATH change, no install.ps1.

| Item | Version | Location |
|------|---------|----------|
| Python venv | Python 3.12.10, pip 26.3 | `.venv\` |
| `relate-db` (import `relate`) | 1.2.0 (`relate.__version__` printed `1.2.0`) | `.venv\Lib\site-packages` |
| `relate.exe` CLI | v1.2.0, Apache-2.0 | `.venv\Scripts\relate.exe` (on PATH only when venv active) |

Files: `requirements.txt` (`relate-db==1.2.0`). Scratch work is in `.scratch\` (should be gitignored).

The pip package does NOT ship the CLI (`.venv\Scripts` only had pip/python after install). The CLI was taken from the GitHub release v1.2.0 asset `relate-windows-amd64.exe` (36,073,472 bytes), downloaded into `.venv\relate-cli-download\` with `SHA256SUMS`. The release publishes `SHA256SUMS` (and a `.sig`, not verified). SHA-256 matched: `b04051a5c1fa2ee22b15816e05b40557dd6e56cfe268ec3088da94eb9625d071`. Only the exe was copied to `.venv\Scripts\relate.exe`; it was only run after the hash check. (The download folder can be deleted.)

## Activate
```
cd "C:\Users\amank\Downloads\neo4j hackathon"
.\.venv\Scripts\Activate.ps1
$env:DO_NOT_TRACK = "1"
```
Activation worked without any execution-policy change here. If it is blocked elsewhere: `Set-ExecutionPolicy -Scope Process Bypass` (process-only), or use `.\.venv\Scripts\python.exe` and `.\.venv\Scripts\relate.exe` directly.

## Results

### Task 4: basic verification: PASS
- `relate --version` -> `Relate v1.2.0 / License: Apache 2.0 (binary)`
- `relate --mode envelope "RETURN 1 AS ok"` -> `{"columnTypes":["INTEGER"],"columns":["ok"],...,"rows":[{"ok":1}],...,"truncated":false}`
- Python `relate.connect(":memory:").execute("RETURN 1 AS ok").fetchall()` -> `[{'ok': 1}]`

### 5a Directory store, JSON codec: PASS
`relate --database jsonstore --snapshot-format json "CREATE (a:Person {name:'Ada'})-[:KNOWS {since:2020}]->(b:Person {name:'Bob'}) RETURN a.name"` then matched it back. Layout:
```
jsonstore\graph.json          human-readable JSON (single line, not pretty-printed)
jsonstore\manifest.json       {"codec":"json","checkpoint_lsn":1,"commit_ts":1,"query_engine":"in-memory","write_engine":"local"}
jsonstore\wal\00000002.log    write-ahead log
jsonstore\wal\.cypherlite.lock / .cypherlite.writer, .cypherlite.lock / .cypherlite.writer  lock files
jsonstore\.relate\schema\schema.cypher
```
graph.json content: `{"value_encoding":2,"nodes":[{"id":0,"labels":["Person"],"properties":{"name":"Ada"}},...],"relationships":[{"id":0,"type":"KNOWS","start_node":0,"end_node":1,"properties":{"since":2020}}],"indexes":[],...}`.
Surprises for diffability: (1) graph.json is ONE LINE (diffs will be poor unless we post-process or use `--pretty`-style export); (2) it is only rewritten at checkpoint (clean close); fresh commits live in `wal\*.log` until then; (3) lock files and the WAL live inside the folder (gitignore them, or commit only after `relate clone`/checkpoint). `relate info --database jsonstore` works cold but reports node counts as "unavailable" for JSON stores.

### 5b KEY CHECK: reader beside a live writer: PASS
Writer: Python script, `autocommit=False`, `CREATE`, `commit()` (printed `relate:N`), sleep 25 s, second write + commit, close. While it held the directory open:
- `relate --database jsonstore --read-only ...` -> succeeded (exit 0).
- `relate --database jsonstore --read-only=live ...` -> succeeded (exit 0).
- A second writer (`relate --database jsonstore ...` without read-only) -> refused: `storage locked: ...\.cypherlite.writer`, exit 5, `"kind":"locked","retryable":false`. Single-writer confirmed.
- Python `relate.connect(dir, read_only=True)` held open across the writer's second commit: result did NOT change (`...W5` before and after). A plain read-only handle is a frozen snapshot taken at open (each new CLI invocation re-snapshots, so it sees everything committed so far).
- `relate serve --mcp stdio --database jsonstore --read-only=live` beside the writer: started cleanly. stderr: `serve: opened the store read-only and following the WAL - the writer's committed frames appear as they land` / `serve: MCP (stdio) serving on stdin/stdout (auth: none)`. JSON-RPC `initialize` -> `serverInfo {"name":"relate-mcp","version":"1.2.0"}`, protocol 2025-03-26. `tools/list` -> `['read_cypher', 'get_schema']`. One long-lived MCP process queried before and after the writer's 2nd commit: first call returned `[...,"W7"]`, second call (same process, writer still open) returned `[...,"W7","W8"]`. So `live` DOES see new commits without restart.
- Note: the `read_cypher` argument is named `statement` (not `query`); a wrong name gives `invalid params: missing string "statement"`.

### 5c Single `.rl` file refuses read-only while writer is open: PASS (as documented)
With a Python writer holding `one.rl`: `relate --database one.rl --read-only ...` -> `storage locked: ...\one.rl`, exit 5; Python `relate.connect('one.rl', read_only=True)` -> `OperationalError: storage locked`. After the writer exited, read-only open worked (`{"c":1}`).

### 5d Vector and full-text SEARCH: PASS (with syntax notes)
```
CREATE VECTOR INDEX doc_vec FOR (d:Doc) ON (d.emb) WITH [d.fw] OPTIONS {indexConfig: {`vector.dimensions`: 3, `vector.similarity_function`: 'cosine'}};
CREATE FULLTEXT INDEX doc_ft FOR (d:Doc) ON EACH [d.title];
MATCH (d:Doc) SEARCH d IN (VECTOR INDEX doc_vec FOR [1.0,0.1,0.0] LIMIT 2) SCORE AS s RETURN d.id, s
  -> {"d.id":1,"s":0.9975}, {"d.id":2,"s":0.5497}
... WHERE d.fw = 'B' LIMIT 2 ...  -> {"d.id":2,"s":0.5497}   (WITH-filter works)
MATCH (d:Doc) SEARCH d IN (FULLTEXT INDEX doc_ft FOR 'search' LIMIT 5) SCORE AS s RETURN d.id, s ORDER BY s DESC
  -> {"d.id":2,"s":0.2269}, {"d.id":3,"s":0.1913}
```
Difference from primer: FULLTEXT `SEARCH` also REQUIRES `LIMIT` (omitting it: `syntax error: parse error: expected LIMIT`). The primer states this only for vector. The `SCORE AS s` clause works. Index syntax `WITH [d.fw]` placement is between `ON (...)` and `OPTIONS`.

### 5e Transactions in Python: PASS
`conn.autocommit = False`; `execute(CREATE ...)`; `commit()` returned the string bookmark `'relate:1'`. A write followed by `rollback()` left count unchanged (1). In the writer tests, successive commits returned `relate:2`, `relate:3`, ... (a global counter in the store).

### 5f Telemetry: done via DO_NOT_TRACK (session only)
`relate telemetry status` initially: `enabled (default)`. I did NOT run `relate telemetry off` because it persists a setting to a config location (likely outside the project, not verified). Instead `$env:DO_NOT_TRACK="1"` was set per session: status -> `disabled (DO_NOT_TRACK)`. Note the CLI prints a telemetry banner on first runs.

## Other notes
- `relate serve` also hosts the HTTP Query API; `relate agent-context` prints an agent briefing; `https://relatedb.ai/llms.txt` was fetched into `.scratch\llms.txt` (useful syntax reference).
- `relate --mode envelope` includes `"truncated":false` and timings, as the primer says.
- Python `execute()` returns a Cursor; use `.fetchall()`.
- Writes via the CLI do a checkpoint on close; Python `close()` likewise.
