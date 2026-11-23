# Day 1 report (2026-11-22)

Detailed logs: [env-setup.md](env-setup.md) (environment and Relate checks) and [licence-check.md](licence-check.md) (data and template licences).

## Done

| Item | Result |
|---|---|
| Local git repo | `git init -b main`. Skeleton folders, Apache-2.0 `LICENSE`, `.gitignore`, `.env.example` and a README stub. **Nothing committed yet.** |
| Python env | `.venv` (Python 3.12.10). `relate-db==1.2.0` is installed only inside it. `requirements.txt` and `requirements-lock.txt` are written. |
| Relate CLI | v1.2.0 in `.venv\Scripts\relate.exe` (official release asset, SHA-256 checked). No global install and no PATH change. |
| Relate behaviour checks | All PASS. Readers can run beside a writer on a directory store, `--read-only=live` follows commits, the MCP server works, vector and full-text SEARCH work, and transactions work. |
| Licence checks | NIST OSCAL catalogs are public domain plus CC0. StrongDM comply is Apache-2.0 (**chosen**). JupiterOne is CC BY-SA (fallback only, kept in a separate folder). |

## Decisions made by the architect

1. **Storage stays a directory store with the JSON codec.** The key Windows check passed. Its MCP server must use `--read-only=live`.
2. **The diff problem is solved with an export.** `graph.json` is one line and is rewritten at checkpoint, so builds close cleanly and also write `exports/graph.pretty.json` for readable diffs.
3. **The policy template set is StrongDM comply.** Its SOC 2 criteria file (`TSC-2017.yml`) will **not** be copied.
4. **We use NIST 800-171 Rev 3**, which has 97 requirements (the plan is corrected). Its mapping to 800-53 comes from NIST's CUI overlay spreadsheet.
5. **The CSF 2.0 to 800-53 ground truth comes from the CSF 2.0 informative references download**, not the older CSF 1.1 mapping file.

## How to activate the environment (PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
```

If scripts are blocked, run this once for the current window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Still open

- **GitHub repo:** not created. The `gh` CLI isn't installed, so the repo needs to be created on github.com (public, topics `relate` and `relate-neo4j-hackathon`) or `gh` installed first.
- **Data download:** NIST files and the StrongDM templates aren't downloaded yet. Then pin commit SHAs in `inputs/nist/SOURCES.md` and `inputs/templates/NOTICE.md`, using the drafts in licence-check.md.
- **Spreadsheet columns:** open `csf2.xlsx` and `sp800-171r3-cui-overlay.xlsx` and record their real columns and relationship types. These are currently unverified.
- **Template copyright holder:** confirm the exact copyright holder line in StrongDM's AUTHORS file.
