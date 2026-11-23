"""CLI for the agent layer, mounted by ``crosswalk.cli``: ``crosswalk packet`` and ``crosswalk agent setup``.

    crosswalk packet AUD-171                      # out/packets/AUD-171-<as_of>.md (deterministic, no AI)
    crosswalk agent setup [--agent claude-code|cursor] [--dry-run] [--undo] [--yes] [--root PATH]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import relate
import typer
from rich.console import Console

os.environ.setdefault("DO_NOT_TRACK", "1")

from crosswalk import agent_setup as S  # noqa: E402
from crosswalk import build as build_mod  # noqa: E402
from crosswalk import coverage as cov  # noqa: E402
from crosswalk import packet as K  # noqa: E402

app = typer.Typer(add_completion=False, help="Agent layer.")
agent_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Wire the Crosswalk agents into Claude Code or Cursor.")
console = Console()
err = Console(stderr=True)

StoreOpt = typer.Option("data/crosswalk", "--store", help="Path to the Relate directory store.")


def _say(line: str = "") -> None:
    console.print(line, markup=False, highlight=False, soft_wrap=True)


def _utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _fail(message: str, code: int = 1) -> typer.Exit:
    err.print(f"error: {message}", markup=False, highlight=False)
    return typer.Exit(code)


@app.command()
def packet(
    audit: str = typer.Argument(..., help="Audit id, e.g. AUD-171."),
    out: Path = typer.Option(Path("."), "--out", help="Project folder; the file goes to <out>/out/packets/."),
    persist: bool = typer.Option(False, "--persist", help="Also store the audit-date claim check (Answer/Claim/Path) in the graph."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the store's date."),
    store: str = StoreOpt,
) -> None:
    """Write the auditor packet: summary table, one section per requirement, open items (no AI)."""
    from crosswalk import claims as claims_mod
    from crosswalk import proposals as proposals_mod

    _utf8()
    path = build_mod.resolve_store(store)
    if not (path / "manifest.json").exists():
        raise _fail(f"no store at {path}; run `crosswalk build` first")
    try:
        conn = cov.open_read_only(store)
    except relate.OperationalError as exc:
        raise _fail("another writer has the store open; close it and retry" if build_mod.is_locked_error(exc) else str(exc), 2)
    try:
        file, pk = K.write_packet(conn, audit, out, as_of)
    except LookupError as exc:
        raise _fail(str(exc.args[0]) if exc.args else str(exc))
    finally:
        conn.close()
    if persist:
        w = proposals_mod.open_writer(store, wait=10)
        try:
            stored = claims_mod.persist(w, pk["checked"]["audit"])
        finally:
            w.close()
        _say(f"stored as {stored['answer']}")
    _say(f"wrote {file}")
    _say(K.summary_line(pk))


@agent_app.command("setup")
def setup(
    agent: str = typer.Option("claude-code", "--agent", help="claude-code (default) or cursor."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; write nothing."),
    undo: bool = typer.Option(False, "--undo", help="Remove exactly what an earlier setup added."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
    root: Path = typer.Option(Path("."), "--root", help="Project folder to configure (default: here)."),
    store: Optional[Path] = typer.Option(None, "--store", help="Crosswalk store (default: <root>/data/crosswalk)."),
    global_skill: bool = typer.Option(False, "--global-skill", help="Also run `relate skill install` (writes OUTSIDE the repo)."),
    skip_selftest: bool = typer.Option(False, "--skip-selftest", help="Do not spawn the servers to test them."),
) -> None:
    """Register the relate and crosswalk MCP servers and the four agent skills for this project."""
    _utf8()
    try:
        if undo:
            _, lines = S.undo_plan(root)
            _say("Crosswalk agent setup: undo")
            _say()
            for line in lines:
                _say(line)
            if dry_run:
                _say("\ndry run: nothing changed.")
                return
            if not yes and not typer.confirm("\nRemove these files?", default=False):
                raise _fail("cancelled; nothing changed")
            for line in S.undo(root):
                _say(line)
            _say("undone.")
            return

        plan = S.make_plan(root, agent, store)
        for line in S.describe(plan, global_skill):
            _say(line)
        if dry_run:
            _say("\ndry run: nothing written, nothing started.")
            return
        if not yes and not typer.confirm("\nWrite these files?", default=False):
            raise _fail("cancelled; nothing written")
        S.apply(plan, global_skill)
        _say(f"\nwrote {sum(1 for a in plan.actions if a.kind != 'unchanged')} file(s) and {S.MANIFEST}")
        if skip_selftest:
            return
        _say("self-test: starting both MCP servers over stdio ...")
        checks = S.selftest(plan.servers, (store or plan.root / "data" / "crosswalk").resolve())
        for c in checks:
            _say(f"{'✔' if c.ok else '✖'} {c.name}: {c.message}")
        if not all(c.ok for c in checks):
            raise _fail("self-test failed; see the fix-it messages above", 1)
        _say("✔ setup complete: restart your agent so it picks up .mcp.json and the skills.")
    except S.SetupError as exc:
        raise _fail(str(exc))
