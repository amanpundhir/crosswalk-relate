"""Crosswalk command line: ``crosswalk build`` and ``crosswalk coverage``."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import relate
import typer
from rich.console import Console
from rich.table import Table

os.environ.setdefault("DO_NOT_TRACK", "1")

# Windows consoles default to cp1252, which cannot print ✔ ⚠ ✖. Use UTF-8 so help and output never crash.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (_stream.encoding or "").lower() not in ("utf-8", "utf8"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from crosswalk import build as build_mod  # noqa: E402
from crosswalk import coverage as cov  # noqa: E402
from crosswalk import queries as Q  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Crosswalk: audit prep on a Relate compliance graph.")
console = Console()
err = Console(stderr=True)

# Human-in-the-loop commands (propose-map, review, decisions) live in review_cli.
from crosswalk import review_cli as _review_cli  # noqa: E402

app.registered_commands.extend(_review_cli.app.registered_commands)

# Agent layer: `crosswalk packet` and `crosswalk agent setup` live in agent_cli.
from crosswalk import agent_cli as _agent_cli  # noqa: E402

app.registered_commands.extend(_agent_cli.app.registered_commands)
app.add_typer(_agent_cli.agent_app, name="agent")

LOCKED_MESSAGE = "another writer has the store open; close it or use a read-only command"
STATUS_STYLE = {"covered": "green", "inherited": "yellow", "gap": "red"}

StoreOpt = typer.Option("data/crosswalk", "--store", help="Path to the Relate directory store.")


def _fail(message: str, code: int = 1) -> typer.Exit:
    err.print(f"[red]error:[/red] {message}")
    return typer.Exit(code)


@app.command()
def build(
    store: str = StoreOpt,
    no_export: bool = typer.Option(False, "--no-export", help="Skip exports/graph.pretty.json."),
) -> None:
    """Rebuild the store (and exports/graph.pretty.json) from the inputs."""
    try:
        res = build_mod.build(store, fresh=True, export=not no_export)
    except build_mod.StoreLockedError as exc:
        raise _fail(f"{LOCKED_MESSAGE} ({exc})", 2)
    except relate.OperationalError as exc:
        if build_mod.is_locked_error(exc):
            raise _fail(LOCKED_MESSAGE, 2)
        raise _fail(str(exc))
    except build_mod.BuildError as exc:
        raise _fail(str(exc))
    console.print(f"[bold]built[/bold] {res.store_dir}  ({res.seconds:.1f}s, {res.size_bytes / 1e6:.2f} MB)")
    t = Table(title="Graph contents")
    t.add_column("Nodes"); t.add_column("#", justify="right")
    t.add_column("Relationships"); t.add_column("#", justify="right")
    n, r = list(res.nodes.items()), list(res.relationships.items())
    for i in range(max(len(n), len(r))):
        a = n[i] if i < len(n) else ("", "")
        b = r[i] if i < len(r) else ("", "")
        t.add_row(a[0], str(a[1]), b[0], str(b[1]))
    t.add_row("[bold]total[/bold]", str(res.total_nodes), "[bold]total[/bold]", str(res.total_relationships))
    console.print(t)
    if res.export_path:
        console.print(f"export: {res.export_path}")


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f}%" if total else "-"


@app.command()
def coverage(
    framework: Optional[str] = typer.Option(None, "--framework", "-f", help="800-171, 800-53 or CSF."),
    audit: Optional[str] = typer.Option(None, "--audit", help="Restrict to an audit scope, e.g. AUD-53 (800-53 MODERATE)."),
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    detail: bool = typer.Option(False, "--detail", help="List every requirement, not just family totals."),
    status: Optional[str] = typer.Option(None, "--status", help="With --detail: only covered, inherited or gap."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """Coverage of a framework as of the demo date, grouped by family."""
    if not framework and not audit:
        raise _fail("give --framework or --audit")
    path = build_mod.resolve_store(store)
    if not (path / "manifest.json").exists():
        raise _fail(f"no store at {path}; run `crosswalk build` first")
    try:
        conn = cov.open_read_only(store)
    except relate.OperationalError as exc:
        raise _fail(LOCKED_MESSAGE if build_mod.is_locked_error(exc) else str(exc), 2)
    try:
        result = Q.coverage(conn, framework, as_of, audit)  # cov.coverage + the path ids (receipts) of every row
    except LookupError as exc:
        raise _fail(str(exc))
    finally:
        conn.close()

    if json_out:
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return

    reqs = result["requirements"]
    fams: dict[str, dict] = {}
    for r in reqs:
        f = fams.setdefault(r["family_id"], {"title": r["family_title"], "covered": 0, "inherited": 0, "gap": 0, "rows": []})
        f[r["status"]] += 1
        f["rows"].append(r)

    scope = f" ({audit}: {result['baseline']} baseline)" if result.get("baseline") else (f" ({audit})" if audit else "")
    table = Table(title=f"{result['framework']}{scope} coverage as of {result['as_of']}")
    if detail:
        table.add_column("Family / requirement"); table.add_column("Status"); table.add_column("Because")
        for fid, f in fams.items():
            table.add_row(f"[bold]{fid.split(':', 1)[-1]}  {f['title']}[/bold]", "",
                          f"{f['covered']} covered, {f['inherited']} inherited, {f['gap']} gap")
            for r in f["rows"]:
                if status and r["status"] != status:
                    continue
                because = ", ".join(r["controls"]) if r["status"] == "covered" else ", ".join(r["via"])
                if r["status"] == "inherited":
                    because = "via " + because
                table.add_row(f"  {r['id']}", f"[{STATUS_STYLE[r['status']]}]{r['status']}[/]", because)
    else:
        table.add_column("Family", no_wrap=True)
        table.add_column("Title")
        for col in ("Reqs", "Covered", "Inherited", "Gaps", "Cov+Inh"):
            table.add_column(col, justify="right", no_wrap=True)
        for fid, f in fams.items():
            total = len(f["rows"])
            table.add_row(fid.split(":", 1)[-1], f["title"], str(total), str(f["covered"]), str(f["inherited"]), str(f["gap"]),
                          _pct(f["covered"] + f["inherited"], total))
    total = result["total"]
    table.add_section()
    if detail:
        table.add_row("[bold]Total[/bold]", "",
                      f"{result['covered']} covered, {result['inherited']} inherited, {result['gaps']} gap of {total}")
    else:
        table.add_row("[bold]Total[/bold]", "", str(total), str(result["covered"]), str(result["inherited"]),
                      str(result["gaps"]), _pct(result["covered"] + result["inherited"], total))
    console.print(table)
    console.print(
        f"covered {result['covered']}/{total} ({_pct(result['covered'], total)}), "
        f"inherited {result['inherited']}, gaps {result['gaps']}"
    )


# --------------------------------------------------------------------------
# Questions Q2, Q3, Q4, Q6 and explain (queries/*.cypher via crosswalk.queries)
# --------------------------------------------------------------------------


def _emit_json(obj) -> None:
    """Print a result as UTF-8 JSON on stdout."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _emit_text(text: str) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _ask(store: str, fn, *args, **kwargs):
    """Open the store read-only, call ``fn(conn, ...)``, close, and turn lookup errors into CLI errors."""
    path = build_mod.resolve_store(store)
    if not (path / "manifest.json").exists():
        raise _fail(f"no store at {path}; run `crosswalk build` first")
    try:
        conn = cov.open_read_only(store)
    except relate.OperationalError as exc:
        raise _fail(LOCKED_MESSAGE if build_mod.is_locked_error(exc) else str(exc), 2)
    try:
        return fn(conn, *args, **kwargs)
    except (LookupError, ValueError) as exc:
        raise _fail(str(exc.args[0]) if exc.args else str(exc))
    finally:
        conn.close()


ID_COLUMNS = {"Requirement", "Control", "Evidence", "Path", "Audit", "Expires", "Date", "Fw"}


def _show(table: Table) -> None:
    """Print a table without truncating id columns (other columns shrink or wrap instead)."""
    for col in table.columns:
        if str(col.header) in ID_COLUMNS:
            col.no_wrap = True
    console.print(table)


def _pid(paths: list[dict]) -> str:
    """First path id of a row plus how many more it has (compact table cell)."""
    if not paths:
        return ""
    return paths[0]["id"] + (f" (+{len(paths) - 1})" if len(paths) > 1 else "")


@app.command()
def suggest(
    control: str = typer.Argument(..., help="Control id, e.g. CTRL-AOTP-4."),
    framework: str = typer.Option("800-53", "--framework", "-f", help="Framework to suggest requirements from."),
    k: int = typer.Option(10, "--k", help="How many suggestions."),
    method: str = typer.Option("hybrid+graph", "--method",
                               help="fulltext | vector | hybrid | hybrid+graph"),
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    store: str = StoreOpt,
) -> None:
    """Candidate requirements a control probably satisfies (search plus graph context). Suggestions only."""
    from crosswalk import suggest as S

    def run(conn):
        try:
            return S.suggest(conn, control, cov.normalise_framework(framework), k=k, method=method)
        except S.SuggestError as exc:
            raise ValueError(str(exc))

    rows = _ask(store, run)
    if json_out:
        _emit_json(rows)
        return
    table = Table(title=f"Suggestions for {control} in {framework} ({method}): not mappings until a human approves")
    for col in ("#", "Requirement", "Title", "Score", "Signals"):
        table.add_column(col)
    for i, r in enumerate(rows, 1):
        signals = r.get("signals") or r.get("contributions") or {}
        def short(val):
            if isinstance(val, dict):
                if "contribution" in val:
                    return f"{val['contribution']:+.3f}"
                if "normalised" in val:
                    return f"{val['normalised']:.2f}"
                return ", ".join(f"{k2} {short(v2)}" for k2, v2 in val.items())
            return f"{val:.3f}" if isinstance(val, (int, float)) else str(val)
        sig = "; ".join(f"{name} {short(val)}"
                        for name, val in (signals.items() if isinstance(signals, dict) else []))
        table.add_row(str(i), r["id"], (r.get("title") or "")[:60], f"{r['score']:.4f}", sig)
    _show(table)


@app.command()
def adopt(
    framework: str = typer.Argument(..., help="Framework to adopt: 800-171 or CSF."),
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """Which requirements of a new framework are already met through the 800-53 crosswalk?"""
    res = _ask(store, Q.adopt, framework, as_of)
    if json_out:
        _emit_json(res)
        return
    table = Table(title=f"Adopting {res['framework']} as of {res['as_of']}: met through the crosswalk (1 hop)")
    for col in ("Requirement", "Title", "Via", "Control", "Evidence", "Path"):
        table.add_column(col)
    for it in res["inherited"]:
        via = [v["neighbour"] for v in it["via"]]
        ctrls = sorted({c["control"] for v in it["via"] for c in v["controls"]}, key=Q.natural_key)
        evs = sorted({e for v in it["via"] for c in v["controls"] for e in c["evidence"]}, key=Q.natural_key)
        table.add_row(it["requirement"], it["title"] or "", "\n".join(via), "\n".join(ctrls),
                      ", ".join(evs), _pid(it["paths"]))
    _show(table)
    n, total = res["inherited_count"], res["active_requirements"]
    console.print(f"{n} of {total} {res['framework']} requirements ({_pct(n, total)}) are already met "
                  f"through the crosswalk; {total - n} still need direct work or a direct mapping.")


@app.command()
def blast(
    days: int = typer.Option(30, "--days", help="Evidence expiring within N days of as_of."),
    until: Optional[str] = typer.Option(None, "--until", help="Evidence expiring on or before this date (YYYY-MM-DD)."),
    audit: Optional[str] = typer.Option(None, "--audit", help="Evidence expiring before this audit's date, e.g. AUD-171."),
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """Blast radius: what loses coverage if evidence expiring in the window is not renewed."""
    if until and audit:
        raise _fail("give --until or --audit, not both")
    res = _ask(store, Q.blast, days, until, audit, as_of)
    if json_out:
        _emit_json(res)
        return
    window = f"{res['as_of']} to {res['cutoff']} ({res['window_days']} days" + (f", {audit}" if audit else "") + ")"
    t = Table(title=f"Evidence expiring in {window}")
    for col in ("Evidence", "Expires", "Controls left bare", "Controls with replacement", "Requested by"):
        t.add_column(col)
    for e in res["expiring_evidence"]:
        t.add_row(e["evidence"], e["expires_at"], ", ".join(e["controls_left_without_valid_evidence"]),
                  ", ".join(e["controls_with_replacement"]), ", ".join(e["requested_by"]))
    _show(t)
    b = Table(title="Requirements that lose direct coverage")
    for col in ("Requirement", "Fw", "Lost control(s)", "After expiry", "Path"):
        b.add_column(col)
    for r in res["broken_requirements"]:
        after = (f"[yellow]still met via {', '.join(r['inherited_via'])}[/]" if r["still_inherited"]
                 else "[red]fully broken[/]")
        b.add_row(r["requirement"], r["framework"], ", ".join(r["controls_lost"]), after, _pid(r["paths"]))
    _show(b)
    a = Table(title="Affected audits")
    for col in ("Audit", "Date", "Days out", "Why"):
        a.add_column(col)
    for x in res["affected_audits"]:
        why = []
        if x["requests_expiring_evidence"]:
            why.append("requests " + ", ".join(x["requests_expiring_evidence"]))
        if x["broken_requirements_in_framework"]:
            why.append(f"{x['broken_requirements_in_framework']} broken {x['framework']} requirement(s)")
        a.add_row(x["audit"], x["date"], str(x["days_after_as_of"]), "; ".join(why))
    _show(a)
    parts = []
    for fw in ("800-171", "800-53", "CSF"):
        rows = [r for r in res["broken_requirements"] if r["framework"] == fw]
        if not rows:
            continue
        still = sum(1 for r in rows if r["still_inherited"])
        detail = f"{len(rows) - still} fully broken, {still} still met via another framework" if still else "all fully broken"
        parts.append(f"{fw}: {len(rows)} lose direct coverage ({detail})")
    console.print("; ".join(parts) if parts else "nothing loses coverage in this window.")


@app.command()
def reuse(
    top: int = typer.Option(10, "--top", help="How many evidence items to show."),
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """Evidence reuse: which valid evidence item backs the most requirements across frameworks?"""
    res = _ask(store, Q.reuse, top, as_of)
    if json_out:
        _emit_json(res)
        return
    t = Table(title=f"Top {len(res)} evidence items by reuse")
    for col in ("#", "Evidence", "Expires", "Controls", "Direct reqs", "Frameworks", "1-hop reach", "Total reach"):
        t.add_column(col, justify="right" if col in {"#", "Controls", "Direct reqs", "1-hop reach", "Total reach"} else "left")
    for r in res:
        t.add_row(str(r["rank"]), r["evidence"], r["expires_at"], str(len(r["controls"])), str(r["direct_count"]),
                  ", ".join(r["frameworks_reached"]), str(len(r["one_hop_requirements"])), str(r["reach_count"]))
    _show(t)


@app.command()
def owners(
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """Owner risk: controls with a single owner, what depends on them, and controls with no owner."""
    res = _ask(store, Q.owner_risk, as_of)
    if json_out:
        _emit_json(res)
        return
    t = Table(title="Sole owners (what if she or he leaves?)")
    for col in ("Person", "Sole-owned", "On high systems", "Reqs only they cover", "Audits affected", "Path"):
        t.add_column(col, justify="right" if col in {"Sole-owned", "On high systems", "Reqs only they cover"} else "left")
    for p, v in sorted(res["people"].items(), key=lambda kv: (-kv[1]["sole_owned_count"], kv[0])):
        if not v["sole_owned_count"]:
            continue
        t.add_row(f"{v['name']} ({p})", str(v["sole_owned_count"]), str(len(v["controls_touching_high_systems"])),
                  str(len(v["requirements_solely_dependent"])), ", ".join(v["audits_affected"]), _pid(v["paths"]))
    _show(t)
    if res["unowned_detail"]:
        u = Table(title="Adopted controls with no owner")
        for col in ("Control", "Status", "Title", "Path"):
            u.add_column(col)
        for d in res["unowned_detail"]:
            u.add_row(d["control"], d["status"] or "", d["title"] or "", _pid(d["paths"]))
        _show(u)
    else:
        console.print("every adopted control has an owner")


@app.command()
def stale(
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    all_rows: bool = typer.Option(False, "--all", help="Also list the Compliant rows the graph agrees with."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """The legacy spreadsheet says Compliant; the graph disagrees (no valid evidence, expired, unowned ...)."""
    res = _ask(store, Q.stale, as_of, all_rows)
    if json_out:
        _emit_json(res)
        return
    t = Table(title=f"Legacy tracker vs the graph as of {res['as_of']}: "
                    f"{res['stale_count']} of {res['marked_compliant']} 'Compliant' rows are contradicted")
    for col in ("Control", "Tracker says", "Reviewed", "The graph says", "Path"):
        t.add_column(col)
    for x in res["stale"]:
        says = "; ".join(i["detail"] for i in x["issues"]) or "consistent"
        paths = [p for i in x["issues"] for p in i["paths"]] or [x["tracker_path"]]
        t.add_row(x["control"], x["tracker"]["status"], x["tracker"]["last_reviewed"] or "", says, _pid(paths))
    _show(t)
    nv = res["no_valid_evidence"]
    console.print(f"{len(nv)} marked Compliant but without valid evidence today: " + (", ".join(nv) or "none"))


@app.command()
def evidence(
    audit: Optional[str] = typer.Option(None, "--audit", help="Only evidence this audit requests, e.g. AUD-171; the cutoff is the audit date."),
    status: Optional[str] = typer.Option(None, "--status", help="expired, expiring, valid or lapsed (expired+expiring); comma separated."),
    until: Optional[str] = typer.Option(None, "--until", help="Cutoff for 'expiring' (YYYY-MM-DD); default the audit date, else as_of + 30 days."),
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """Evidence with collected/expiry dates and status at as_of (expired, expiring by the cutoff, valid)."""
    res = _ask(store, Q.evidence, audit, status, until, as_of)
    if json_out:
        _emit_json(res)
        return
    scope = f", requested by {audit}" if audit else ""
    t = Table(title=f"Evidence as of {res['as_of']} (cutoff {res['cutoff']}{scope}): "
                    f"{res['counts']['expired']} expired, {res['counts']['expiring']} expiring, "
                    f"{res['counts']['valid']} valid")
    for col in ("Evidence", "Collected", "Expires", "Status", "Days", "Controls", "Requested by", "Path"):
        t.add_column(col, justify="right" if col == "Days" else "left")
    for e in res["evidence"]:
        style = {"expired": "red", "expiring": "yellow", "valid": "green"}[e["status"]]
        t.add_row(e["evidence"], e["collected_at"], e["expires_at"], f"[{style}]{e['status']}[/]",
                  str(e["days_to_expiry"]), ", ".join(e["controls"]),
                  ", ".join(x["audit"] for x in e["requested_by"]), _pid(e["proves_paths"] + e["request_paths"]))
    _show(t)
    console.print(f"{res['shown']} shown: " + (", ".join(res["evidence_ids"]) or "none"))


def _explain_status(res: dict) -> str:
    return "covered" if res["covered_direct"] else ("inherited" if res["inherited"] else "gap")


def _explain_markdown(res: dict) -> str:
    st = _explain_status(res)
    lines = [f"# {res['requirement']}: {res['title']}", "",
             f"Status as of {res['as_of']}: **{st.upper()}**"
             + (f" (via {', '.join(res['inherited_via'])})" if st == "inherited" else ""), ""]
    lines += ["## Direct paths (requirement <- control <- evidence)", ""]
    if res["paths"]:
        lines += ["| Control | Owner | Mapping approved | Evidence | Collected | Expires | Valid | Path |",
                  "|---|---|---|---|---|---|---|---|"]
        for p in res["paths"]:
            lines.append("| {c} | {o} | {a} {d} | {e} | {col} | {exp} | {v} | `{pid}` |".format(
                c=p["control"], o=", ".join(p["control_owners"]) or "none", a=p["mapping_approved_by"],
                d=p["mapping_approved_at"], e=p["evidence"] or "none", col=p.get("collected_at") or "",
                exp=p.get("expires_at") or "", v="yes" if p["valid"] else "NO", pid=p["path_id"]))
    else:
        lines.append("No adopted control is mapped to this requirement.")
    if res["inherited_paths"]:
        lines += ["", "## Inherited paths (1 crosswalk hop)", "", "| Neighbour | Control | Evidence | Expires | Path |",
                  "|---|---|---|---|---|"]
        for p in res["inherited_paths"]:
            lines.append(f"| {p['neighbour']} | {p['control']} | {p['evidence']} | {p['expires_at']} | `{p['id']}` |")
    if res["proposals"]:
        lines += ["", "## Proposed mappings (not approved)", "", "| Proposal | Control | Status | Decision |", "|---|---|---|---|"]
        for d in res["proposals"]:
            dec = f"{d['decision']} by {d['decided_by']} on {d['decided_at']}: {d['reason']}" if d.get("decision") else ""
            lines.append(f"| {d['proposal']} | {d['control']} | {d['status']} | {dec} |")
    return "\n".join(lines) + "\n"


@app.command()
def explain(
    requirement: str = typer.Argument(..., help="Requirement id, e.g. 800-171:03.05.03 (or just 03.05.03)."),
    md: bool = typer.Option(False, "--md", help="Print Markdown instead of tables."),
    json_out: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Override the date (default: Meta.as_of)."),
    store: str = StoreOpt,
) -> None:
    """Why a requirement is covered, inherited or a gap: control and evidence paths with dates."""
    def _go(conn):
        return Q.explain(conn, Q.resolve_requirement(conn, requirement), as_of)

    res = _ask(store, _go)
    if json_out:
        _emit_json(res)
        return
    if md:
        _emit_text(_explain_markdown(res))
        return
    st = _explain_status(res)
    style = STATUS_STYLE[st]
    console.print(f"[bold]{res['requirement']}[/bold]  {res['title']}")
    console.print(f"as of {res['as_of']}: [{style}]{st}[/]"
                  + (f" via {', '.join(res['inherited_via'])}" if st == "inherited" else ""))
    t = Table(title="Direct paths (requirement <- control <- evidence)")
    for col in ("Control", "Owner", "Mapping", "Evidence", "Collected", "Expires", "Valid", "Path"):
        t.add_column(col)
    for p in res["paths"]:
        t.add_row(p["control"], ", ".join(p["control_owners"]) or "none",
                  f"{p['mapping_approved_by']} {p['mapping_approved_at']}", p["evidence"] or "none",
                  p.get("collected_at") or "", p.get("expires_at") or "",
                  "[green]valid[/]" if p["valid"] else "[red]no[/]", p["path_id"])
    _show(t)
    if res["inherited_paths"]:
        i = Table(title="Inherited paths (1 crosswalk hop)")
        for col in ("Neighbour", "Control", "Evidence", "Expires", "Path"):
            i.add_column(col)
        for p in res["inherited_paths"]:
            i.add_row(p["neighbour"], p["control"], p["evidence"], p["expires_at"], p["id"])
        _show(i)
    for d in res["proposals"]:
        dec = f"{d['decision']} by {d['decided_by']} on {d['decided_at']}: {d['reason']}" if d.get("decision") else d["status"]
        console.print(f"proposed, not approved: {d['proposal']} {d['control']} ({dec})")


# --------------------------------------------------------------------------
# Claim checker and the live-catch demo (crosswalk.claims, crosswalk.demo_live)
# --------------------------------------------------------------------------

demo_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Replayable demos (no API key needed).")
app.add_typer(demo_app, name="demo")
_SYMBOL_STYLE = {"✔": "green", "⚠": "yellow", "✖": "red"}


def _utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _print_checked_line(line: str) -> None:
    stripped = line.lstrip()
    style = _SYMBOL_STYLE.get(stripped[:1])
    console.print(line, style=style, markup=False, highlight=False, soft_wrap=True)


@app.command()
def check(
    answer: Path = typer.Argument(..., help="Answer JSON: {question, agent, claims: [{text, path_ids}]}."),
    json_out: bool = typer.Option(False, "--json", help="Print the full checked answer as JSON."),
    persist: bool = typer.Option(False, "--persist", help="Also store Answer/Claim/Path nodes in the graph."),
    store: str = StoreOpt,
) -> None:
    """Re-run every path an answer cites: prints ✔/⚠/✖ per claim with the reason (exit 1 if any claim is not ✔)."""
    from crosswalk import claims as claims_mod
    from crosswalk import proposals as proposals_mod

    def _go(conn):
        try:
            checked = claims_mod.check_claims(conn, claims_mod.load_answer(answer))
        except claims_mod.ClaimsError as exc:
            raise ValueError(str(exc))
        return checked, claims_mod.corrected_answer(conn, checked)

    checked, corrected = _ask(store, _go)
    if persist:
        try:
            w = proposals_mod.open_writer(store, wait=10)
        except relate.OperationalError as exc:
            raise _fail(LOCKED_MESSAGE if build_mod.is_locked_error(exc) else str(exc), 2)
        try:
            checked["persisted"] = claims_mod.persist(w, checked)
        finally:
            w.close()
    if json_out:
        _emit_json({**checked, "corrected": corrected})
    else:
        _utf8_stdout()
        if checked.get("question"):
            console.print(f"Question: {checked['question']}", markup=False, highlight=False)
        for line in claims_mod.render_lines(checked):
            _print_checked_line(line)
        console.print(f"Corrected: {corrected['text']}", markup=False, highlight=False, soft_wrap=True)
        if checked.get("persisted"):
            console.print(f"stored as {checked['persisted']['answer']}", markup=False, highlight=False)
    if checked["counts"]["verified"] != checked["counts"]["claims"]:
        raise typer.Exit(1)


@demo_app.command("live-catch")
def demo_live_catch(
    store: str = StoreOpt,
    answer: Optional[Path] = typer.Option(None, "--answer", help="Recorded answer (default eval/agent-runs/live-catch-recorded.json)."),
    no_draft: bool = typer.Option(False, "--no-draft", help="Do not draft the evidence-renewal request."),
) -> None:
    """Replay the recorded 'Is MFA covered?' answer on a fresh store copy; the claim check runs live."""
    from crosswalk import claims as claims_mod
    from crosswalk import demo_live

    _utf8_stdout()
    try:
        demo_live.run(store, answer, draft=not no_draft, echo=_print_checked_line)
    except (claims_mod.ClaimsError, LookupError, FileNotFoundError) as exc:
        raise _fail(str(exc))
    except relate.OperationalError as exc:
        raise _fail(LOCKED_MESSAGE if build_mod.is_locked_error(exc) else str(exc), 2)


@app.command()
def scorecard(
    store: str = StoreOpt,
    json_out: bool = typer.Option(False, "--json", help="Print the scorecard JSON."),
    quick: bool = typer.Option(False, "--quick", help="Skip the build timing and concurrency demos; one live-catch replay."),
) -> None:
    """Compute the KPIs of docs/plan/05 (no AI) and write eval/scorecard.json and eval/scorecard.md."""
    from crosswalk import scorecard as sc_mod

    _utf8_stdout()
    try:
        sc = sc_mod.run(store, quick=quick)
    except (FileNotFoundError, relate.OperationalError) as exc:
        raise _fail(LOCKED_MESSAGE if isinstance(exc, relate.OperationalError) and build_mod.is_locked_error(exc) else str(exc))
    if json_out:
        _emit_json(sc)
        return
    for h in sc["headline"]:
        console.print(f"[bold]{h['row']}:[/bold] {h['value']}")
    s = sc["summary"]
    console.print(f"pass {s['pass']}, miss {s['miss']}, info {s['info']}" + (f"  missed: {', '.join(s['misses'])}" if s["misses"] else ""))
    console.print("wrote eval/scorecard.json and eval/scorecard.md")


def main() -> None:
    try:
        app()
    except relate.OperationalError as exc:
        if build_mod.is_locked_error(exc):
            err.print(f"[red]error:[/red] {LOCKED_MESSAGE}")
            raise SystemExit(2)
        raise


if __name__ == "__main__":
    main()
