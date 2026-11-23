"""Human-in-the-loop commands, as a Typer sub-app the main CLI mounts (``app.add_typer(review_cli.app)``
or by registering the three functions): ``propose-map``, ``review``, ``decisions``.

    crosswalk propose-map CTRL-REAP-6 '800-53:IA-2(8)' --rationale "..."   # writes a verified :Proposal
    crosswalk review                                                      # interactive queue
    crosswalk review --approve PR-9 --reason "restore tests are CP-4"     # one decision, no prompts
    crosswalk review --reject PR-10 --reason "SC-8 is data in transit"
    crosswalk decisions --about CTRL-AOTP-11                              # memory agents must read first

All writes open the directory store as its single writer (``autocommit=False``) and wait a few
seconds for another writer to finish before giving up with exit code 2.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import relate
import typer
from rich.console import Console
from rich.table import Table

os.environ.setdefault("DO_NOT_TRACK", "1")

from crosswalk import proposals as P  # noqa: E402
from crosswalk import review as R  # noqa: E402
from crosswalk.coverage import open_read_only  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Propose mappings, review the queue, read past decisions.")
console = Console()
err = Console(stderr=True)

StoreOpt = typer.Option("data/crosswalk", "--store", help="Path to the Relate directory store.")
LOCK_WAIT = 5.0
DEFAULT_REVIEWER = "P-maya-chen"


def _fail(message: str, code: int = 1) -> typer.Exit:
    err.print(f"[red]error:[/red] {message}")
    return typer.Exit(code)


def _writer(store: str) -> relate.Connection:
    try:
        return P.open_writer(store, wait=LOCK_WAIT)
    except relate.OperationalError as exc:
        if P.is_locked(exc):
            raise _fail("another writer has the store open; close it and try again", 2)
        raise _fail(str(exc))


def _reader(store: str) -> relate.Connection:
    try:
        return open_read_only(store)
    except relate.OperationalError as exc:
        raise _fail(str(exc))


def _badge(verified: bool | None) -> str:
    return {True: "[green]verified[/green]", False: "[red]FAILED[/red]"}.get(verified, "[yellow]unverified[/yellow]")


def _show(p: dict) -> None:
    tgt = f" -> {p['target']}" if p.get("target") else ""
    console.print(f"[bold]{p['id']}[/bold]  {p['kind']}  {p['about']}{tgt}   by {p.get('by')}   "
                  f"{p.get('created_at')}   {_badge(p.get('verified'))}")
    console.print(f"  rationale: {p.get('rationale')}")
    if p.get("draft"):
        console.print(f"  draft: {p['draft']}")
    if p.get("new_status"):
        console.print(f"  status: {p.get('old_status')} -> {p['new_status']}")
    for c in p.get("checks", []):
        mark = "[green]ok[/green]" if c["ok"] else "[red]FAIL[/red]"
        if c.get("info"):
            mark = "[cyan]note[/cyan]"
        console.print(f"    {mark} {c['check']}: {c['detail']}")
    if p.get("verified") is None:
        console.print("    [yellow]not verified yet: it will be checked when you decide[/yellow]")


@app.command("propose-map")
def propose_map(
    control: str = typer.Argument(..., help="Control id, e.g. CTRL-REAP-6."),
    requirement: str = typer.Argument(..., help="Requirement id, e.g. '800-53:IA-2(8)' or a short id."),
    rationale: str = typer.Option(..., "--rationale", "-r", help="Why the control satisfies the requirement."),
    by: str = typer.Option("mapper-agent", "--by", help="Agent (or person) proposing."),
    store: str = StoreOpt,
    json_out: bool = typer.Option(False, "--json", help="Print the stored proposal as JSON."),
) -> None:
    """Write a :Proposal (never a SATISFIES) and show what the verifier said."""
    conn = _writer(store)
    try:
        prop = P.create_proposal(conn, "map", by, control, requirement, rationale)
    finally:
        conn.close()
    if json_out:
        typer.echo(json.dumps(prop, indent=2, ensure_ascii=False))
        return
    console.print(f"[bold]{prop['id']}[/bold] stored as pending ({prop['bookmark']}): {_badge(prop['verified'])}")
    _show({**prop, "created_at": prop["created_at"]})


@app.command()
def review(
    approve: Optional[str] = typer.Option(None, "--approve", help="Proposal id to approve (non-interactive)."),
    reject: Optional[str] = typer.Option(None, "--reject", help="Proposal id to reject (non-interactive)."),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason for the decision (required with --approve/--reject)."),
    by: str = typer.Option(DEFAULT_REVIEWER, "--by", help="Reviewer id recorded on the decision."),
    force: bool = typer.Option(False, "--force", help="Approve even though verification failed (recorded)."),
    list_only: bool = typer.Option(False, "--list", help="Only list the pending proposals."),
    store: str = StoreOpt,
    json_out: bool = typer.Option(False, "--json", help="Print results as JSON."),
) -> None:
    """Review pending proposals: interactively, or one decision with --approve / --reject."""
    if approve and reject:
        raise _fail("give --approve or --reject, not both", 2)
    if list_only:
        conn = _reader(store)
        try:
            queue = R.pending(conn)
        finally:
            conn.close()
        if json_out:
            typer.echo(json.dumps(queue, indent=2, ensure_ascii=False))
            return
        _table(queue)
        return
    if approve or reject:
        if not reason:
            raise _fail("--reason is required: the reason is stored and agents read it", 2)
        pid, outcome = (approve or reject), ("approved" if approve else "rejected")
        _decide_and_report(store, pid, outcome, by, reason, force, json_out)
        return
    _interactive(store, by, force)


def _table(queue: list[dict]) -> None:
    if not queue:
        console.print("no pending proposals")
        return
    t = Table(title=f"{len(queue)} pending proposals")
    for col in ("id", "kind", "about", "target", "by", "verified", "why", "path"):
        t.add_column(col, no_wrap=col in ("id", "path"))
    for p in queue:
        why = (p.get("verify_reason") or "not verified yet")
        ids = p.get("path_ids") or []
        t.add_row(p["id"], p["kind"], p["about"] or "", p["target"] or p.get("new_status") or "", p["by"] or "",
                  {True: "yes", False: "NO"}.get(p["verified"], "?"), why[:90],
                  (ids[-1] if ids else "") + (f" (+{len(ids) - 1})" if len(ids) > 1 else ""))
    console.print(t)


def _decide_and_report(store, pid, outcome, by, reason, force, json_out) -> None:
    conn = _writer(store)
    try:
        bookmark = R.decide(conn, pid, outcome, by, reason, force=force)
    except R.ReviewError as exc:
        raise _fail(str(exc))
    finally:
        conn.close()
    if json_out:
        typer.echo(json.dumps({"proposal": P.normalise_id(pid, "PR"), "outcome": outcome, "by": by,
                               "reason": reason, "bookmark": bookmark}))
    else:
        console.print(f"[green]{outcome}[/green] {P.normalise_id(pid, 'PR')} by {by} ({bookmark})")


def _interactive(store: str, by: str, force: bool) -> None:
    conn = _writer(store)
    try:
        queue = R.pending(conn)
        if not queue:
            console.print("no pending proposals")
            return
        console.print(f"{len(queue)} pending proposals; reviewing as [bold]{by}[/bold]")
        done = 0
        for p in queue:
            console.rule(p["id"])
            _show(p)
            while True:
                choice = typer.prompt("[a]pprove / [r]eject / [s]kip / [q]uit", default="s").strip().lower()[:1]
                if choice in ("a", "r", "s", "q"):
                    break
            if choice == "q":
                break
            if choice == "s":
                continue
            outcome = "approved" if choice == "a" else "rejected"
            why = typer.prompt("Reason (stored; agents read it)").strip()
            use_force = force
            if outcome == "approved" and p.get("verified") is False and not force:
                use_force = typer.confirm("Verification FAILED. Approve anyway (recorded as forced)?", default=False)
                if not use_force:
                    continue
            try:
                bookmark = R.decide(conn, p["id"], outcome, by, why, force=use_force)
            except R.ReviewError as exc:
                err.print(f"[red]error:[/red] {exc}")
                continue
            done += 1
            console.print(f"[green]{outcome}[/green] {p['id']} ({bookmark})")
        console.print(f"{done} decided")
    finally:
        conn.close()


@app.command()
def decisions(
    about: Optional[str] = typer.Option(None, "--about", help="A control, requirement, evidence or person id."),
    store: str = StoreOpt,
    json_out: bool = typer.Option(False, "--json", help="Print as JSON."),
) -> None:
    """List earlier approvals and rejections with their reasons (read this before proposing)."""
    conn = _reader(store)
    try:
        rows = R.decisions(conn, about)
    finally:
        conn.close()
    if json_out:
        typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if not rows:
        console.print("no decisions" + (f" about {about}" if about else ""))
        return
    t = Table(title="Decisions" + (f" about {about}" if about else ""))
    for col in ("id", "outcome", "by", "at", "about", "target", "relation", "reason", "path"):
        t.add_column(col, no_wrap=col in ("id", "path"))
    for r in rows:
        t.add_row(r["id"], r["outcome"], r["by"], r["at"], r["about"] or "", r["target"] or "", r["relation"],
                  r["reason"], (r["path_ids"][0] + (f" (+{len(r['path_ids']) - 1})" if len(r["path_ids"]) > 1 else ""))
                  if r.get("path_ids") else "")
    console.print(t)


if __name__ == "__main__":
    app()
