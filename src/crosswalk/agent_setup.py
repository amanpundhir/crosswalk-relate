"""``crosswalk agent setup``: one command that wires the Crosswalk agents into Claude Code or Cursor.

Project-scoped only: every file is written under ``--root`` (the repo), never in the user's home directory.

Claude Code
    ``.mcp.json``                       two stdio MCP servers: ``relate`` (read-only live) and ``crosswalk``
    ``.claude/skills/<name>/SKILL.md``  the four role skills, copied from ``agents/skills/``
Cursor
    ``.cursor/mcp.json``                the same two servers
    ``.cursor/rules/<name>.mdc``        the same four skills as rules

Safety: the plan of every file is shown before anything is written (confirm unless ``--yes``); a file that
already exists and is not ours is copied to ``<file>.bak`` first; everything created is recorded in
``.crosswalk-setup.json`` so ``--undo`` removes exactly that and restores the backups.

``relate skill install`` (Relate's own skill bundle) has no project scope or output directory (only
``--agent`` and ``--force``), so it writes into the user's global agent skills folder.  It is therefore NOT
run by default: the plan prints the command and ``--global-skill`` runs it.

After writing, a self-test spawns both MCP servers over stdio and calls relate ``get_schema`` and crosswalk
``coverage`` (800-171).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SKILLS = ("crosswalk-audit-prep", "crosswalk-mapper", "crosswalk-evidence", "crosswalk-auditor-packet")
MANIFEST = ".crosswalk-setup.json"
AGENTS = ("claude-code", "cursor")
REPO_ROOT = Path(__file__).resolve().parents[2]
SELFTEST_TIMEOUT = 90


class SetupError(Exception):
    pass


# --------------------------------------------------------------------------
# what to write
# --------------------------------------------------------------------------


@dataclass
class Action:
    path: Path                 # absolute
    kind: str                  # create | overwrite | unchanged
    content: str
    backup: bool = False       # an existing file that is not ours is copied to <file>.bak first
    note: str = ""


@dataclass
class Plan:
    root: Path
    agent: str
    actions: list[Action] = field(default_factory=list)
    servers: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    global_skill_cmd: str = ""

    def rel(self, p: Path) -> str:
        return os.path.relpath(p, self.root)


def scripts_dir(root: Path) -> Path:
    """Where relate.exe and crosswalk-mcp.exe live: the project's venv, else this interpreter's."""
    for cand in (root / ".venv" / "Scripts", root / ".venv" / "bin"):
        if cand.is_dir():
            return cand
    return Path(sys.executable).resolve().parent


def _exe(folder: Path, name: str) -> Path | None:
    for cand in (folder / f"{name}.exe", folder / name):
        if cand.exists():
            return cand
    return None


def server_config(root: Path, store: Path, agent: str) -> tuple[dict[str, dict], list[str]]:
    """``{name: {command, args, env}}`` for the two servers, with absolute paths, plus notes."""
    folder, notes = scripts_dir(root), []
    relate_exe = _exe(folder, "relate")
    if relate_exe is None:
        raise SetupError(f"relate is not installed in {folder}. Install it with: pip install relate-db==1.2.0")
    mcp_exe = _exe(folder, "crosswalk-mcp")
    if mcp_exe is not None:
        cw = {"command": str(mcp_exe), "args": []}
    else:  # an editable install made before the script existed: run the module instead
        py = _exe(folder, "python") or Path(sys.executable)
        cw = {"command": str(py), "args": ["-m", "crosswalk_mcp.server"]}
        notes.append(f"{folder}\\crosswalk-mcp.exe not found (re-run `pip install -e .` to create it): "
                     f"using `python -m crosswalk_mcp.server` instead")
    cw["env"] = {"CROSSWALK_STORE": str(store), "DO_NOT_TRACK": "1"}
    rl = {"command": str(relate_exe),
          "args": ["serve", "--mcp", "stdio", "--database", str(store), "--read-only=live"],
          "env": {"DO_NOT_TRACK": "1"}}
    if agent == "claude-code":
        rl, cw = {"type": "stdio", **rl}, {"type": "stdio", **cw}
    return {"relate": rl, "crosswalk": cw}, notes


def skills_source(root: Path) -> Path:
    for cand in (root / "agents" / "skills", REPO_ROOT / "agents" / "skills"):
        if all((cand / n / "SKILL.md").exists() for n in SKILLS):
            return cand
    raise SetupError("the four skills are missing: expected agents/skills/<name>/SKILL.md for " + ", ".join(SKILLS))


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip():
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def _mdc(text: str) -> str:
    meta, body = _split_frontmatter(text)
    return f"---\ndescription: {meta.get('description', '')}\nalwaysApply: false\n---\n{body}"


def _existing_mcp(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SetupError(f"{path} is not valid JSON ({exc}); fix or remove it, then re-run") from None
    if not isinstance(data, dict):
        raise SetupError(f"{path} is not a JSON object")
    return data


def load_manifest(root: Path) -> dict | None:
    p = root / MANIFEST
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise SetupError(f"{p} is not valid JSON; delete it by hand if you are sure nothing needs undoing") from None


def make_plan(root: Path, agent: str = "claude-code", store: Path | None = None) -> Plan:
    if agent not in AGENTS:
        raise SetupError(f"unknown agent {agent!r}; choose one of {', '.join(AGENTS)}")
    root = root.resolve()
    store = (store or root / "data" / "crosswalk").resolve()
    if not (store / "manifest.json").exists():
        raise SetupError(f"no Crosswalk store at {store}. Run `crosswalk build` first (or pass --store).")
    plan = Plan(root=root, agent=agent)
    plan.servers, plan.notes = server_config(root, store, agent)
    ours = set((load_manifest(root) or {}).get("created", []))

    mcp_path = root / (".mcp.json" if agent == "claude-code" else ".cursor/mcp.json")
    data = _existing_mcp(mcp_path)
    data.setdefault("mcpServers", {}).update(plan.servers)
    plan.actions.append(_action(plan, mcp_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", ours,
                                "merged into the existing file (other servers kept)" if mcp_path.exists() else ""))

    src = skills_source(root)
    for name in SKILLS:
        text = (src / name / "SKILL.md").read_text(encoding="utf-8")
        if agent == "claude-code":
            plan.actions.append(_action(plan, root / ".claude" / "skills" / name / "SKILL.md", text, ours))
        else:
            plan.actions.append(_action(plan, root / ".cursor" / "rules" / f"{name}.mdc", _mdc(text), ours))
    plan.global_skill_cmd = f"relate skill install --agent {'claude-code' if agent == 'claude-code' else agent}"
    return plan


def _action(plan: Plan, path: Path, content: str, ours: set[str], note: str = "") -> Action:
    rel = plan.rel(path).replace("\\", "/")
    if not path.exists():
        return Action(path, "create", content, note=note)
    if path.read_text(encoding="utf-8") == content:
        return Action(path, "unchanged", content)
    return Action(path, "overwrite", content, backup=rel not in ours, note=note)


def describe(plan: Plan, global_skill: bool = False) -> list[str]:
    lines = [f"Crosswalk agent setup for {plan.agent} in {plan.root}", ""]
    for a in plan.actions:
        extra = " (backup to " + plan.rel(a.path) + ".bak first)" if a.backup else ""
        lines.append(f"  {a.kind:<9} {plan.rel(a.path)}{extra}" + (f"  [{a.note}]" if a.note else ""))
    lines.append(f"  write     {MANIFEST}  (lists exactly what this run added, for --undo)")
    lines.append("")
    for name, cfg in plan.servers.items():
        lines.append(f"  MCP server '{name}': {cfg['command']} {' '.join(cfg['args'])}")
    lines += [f"  note: {n}" for n in plan.notes]
    lines.append("")
    if global_skill:
        lines.append(f"  will run: {plan.global_skill_cmd}   (writes into your GLOBAL agent skills folder)")
    else:
        lines.append(f"  not run: {plan.global_skill_cmd}")
        lines.append("           `relate skill install` has no project scope or output directory (only --agent and --force),")
        lines.append("           so it would write outside this repo. Add --global-skill to run it.")
    lines.append("  nothing outside this folder is touched.")
    return lines


# --------------------------------------------------------------------------
# apply and undo
# --------------------------------------------------------------------------


def apply(plan: Plan, global_skill: bool = False) -> dict:
    """Write the plan and the manifest; returns the manifest."""
    root = plan.root
    old = load_manifest(root) or {"created": [], "backups": {}, "dirs": [], "global_skill": None}
    created, backups, dirs = list(old["created"]), dict(old["backups"]), list(old["dirs"])
    for a in plan.actions:
        rel = plan.rel(a.path).replace("\\", "/")
        if a.kind == "unchanged":
            continue
        if a.backup:
            bak = a.path.with_name(a.path.name + ".bak")
            shutil.copy2(a.path, bak)
            backups[rel] = plan.rel(bak).replace("\\", "/")
        missing = []
        d = a.path.parent
        while d != root and not d.exists():
            missing.append(d)
            d = d.parent
        a.path.parent.mkdir(parents=True, exist_ok=True)
        for m in reversed(missing):
            dirs.append(plan.rel(m).replace("\\", "/"))
        a.path.write_text(a.content, encoding="utf-8", newline="\n")
        if rel not in created:
            created.append(rel)
    ran = None
    if global_skill:
        exe = _exe(scripts_dir(root), "relate")
        res = subprocess.run([str(exe), *plan.global_skill_cmd.split()[1:]], capture_output=True, text=True,
                             env={**os.environ, "DO_NOT_TRACK": "1"})
        ran = {"command": plan.global_skill_cmd, "exit": res.returncode,
               "undo": plan.global_skill_cmd.replace("install", "remove")}
    manifest = {"agent": plan.agent, "created": created, "backups": backups, "dirs": dirs, "global_skill": ran or old.get("global_skill")}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def undo_plan(root: Path) -> tuple[dict, list[str]]:
    m = load_manifest(root.resolve())
    if m is None:
        raise SetupError(f"nothing to undo: no {MANIFEST} in {root}")
    lines = []
    for rel in m["created"]:
        lines.append(f"  restore   {rel}  (from {m['backups'][rel]})" if rel in m["backups"] else f"  remove    {rel}")
    for rel in sorted(m["dirs"], key=len, reverse=True):
        lines.append(f"  rmdir     {rel}  (only if empty)")
    lines.append(f"  remove    {MANIFEST}")
    if m.get("global_skill"):
        lines.append(f"  note: the global skill is not touched; run `{m['global_skill']['undo']}` yourself to remove it")
    return m, lines


def undo(root: Path) -> list[str]:
    root = root.resolve()
    m, _ = undo_plan(root)
    done = []
    for rel in m["created"]:
        p = root / rel
        bak = m["backups"].get(rel)
        if bak and (root / bak).exists():
            os.replace(root / bak, p)
            done.append(f"restored {rel}")
        elif p.exists():
            p.unlink()
            done.append(f"removed {rel}")
    for rel in sorted(m["dirs"], key=len, reverse=True):
        try:
            (root / rel).rmdir()
        except OSError:
            pass
    (root / MANIFEST).unlink(missing_ok=True)
    return done


# --------------------------------------------------------------------------
# self-test: spawn both servers over stdio
# --------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    ok: bool
    message: str


def _payload(result: Any) -> Any:
    sc = getattr(result, "structuredContent", None)
    if sc:
        return sc["result"] if set(sc) == {"result"} else sc
    text = result.content[0].text if result.content else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def _call_server(name: str, cfg: dict, tool: str, args: dict, errlog: Any) -> Any:
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=cfg["command"], args=list(cfg.get("args", [])), env=dict(cfg.get("env") or {}))
    with anyio.fail_after(SELFTEST_TIMEOUT):
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                if tool not in tools:
                    raise RuntimeError(f"server {name} has no tool {tool!r} (it offers: {', '.join(sorted(tools))})")
                res = await session.call_tool(tool, args)
                if res.isError:
                    raise RuntimeError(f"{tool} returned an error: {res.content[0].text if res.content else ''}")
                return _payload(res)


def selftest(servers: dict[str, dict], store: Path) -> list[Check]:
    import anyio

    checks: list[Check] = []
    fix_store = f"Run `crosswalk build` to create {store}, or pass --store."
    for name, tool, args in (("relate", "get_schema", {}), ("crosswalk", "coverage", {"framework": "800-171"})):
        label = f"{name} {tool}" + (" 800-171" if args else "")
        log = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")  # the server's stderr: shown only on failure
        try:
            out = anyio.run(_call_server, name, servers[name], tool, args, log)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a fix-it message
            log.seek(0)
            tail = " ".join(log.read().split())[-200:]
            msg = _unwrap(exc) + (f" (server said: {tail})" if tail else "")
            hint = fix_store if "store" in msg.lower() and "no " in msg.lower() else (
                "Another process may hold the store; close `crosswalk review`/`relate serve` and retry."
                if "lock" in msg.lower() else
                f"Check that {servers[name]['command']} runs, then re-run `crosswalk agent setup`.")
            checks.append(Check(label, False, f"{msg[:300]}. {hint}"))
            log.close()
            continue
        if name == "relate":
            text = out if isinstance(out, str) else json.dumps(out)
            ok = "Requirement" in text and "Control" in text
            checks.append(Check(label, ok, "schema lists Requirement, Control, Evidence ..."
                                if ok else "schema does not list Requirement/Control: is this the Crosswalk store?"))
        else:
            ok = isinstance(out, dict) and out.get("total") == 97
            checks.append(Check(label, ok, (f"{out['covered']}/{out['total']} covered, {out['inherited']} inherited, "
                                            f"{out['gaps']} gaps as of {out['as_of']}") if ok
                                else f"unexpected result: {str(out)[:200]}"))
        log.close()
    return checks


def _unwrap(exc: BaseException) -> str:
    subs = getattr(exc, "exceptions", None)
    if subs:
        return "; ".join(_unwrap(e) for e in subs)
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
