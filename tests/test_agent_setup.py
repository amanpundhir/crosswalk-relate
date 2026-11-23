"""``crosswalk agent setup`` and ``crosswalk packet``: temp project roots, real MCP servers over stdio.

Nothing here touches the repo's own .mcp.json or data/crosswalk: the store is a copy under tmp_path.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crosswalk import agent_setup as S
from crosswalk.cli import app

REPO = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.fixture(scope="module")
def store_copy(tmp_path_factory) -> Path:
    dest = tmp_path_factory.mktemp("agent-store") / "crosswalk"
    shutil.copytree(REPO / "data" / "crosswalk", dest)
    return dest


@pytest.fixture()
def root(tmp_path, store_copy) -> Path:
    (tmp_path / "data").mkdir()
    shutil.copytree(store_copy, tmp_path / "data" / "crosswalk")
    return tmp_path


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if "data" not in p.relative_to(root).parts[:1]}


def _run(*args: str):
    return runner.invoke(app, list(args))


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------


def test_dry_run_writes_nothing(root):
    before = _tree(root)
    res = _run("agent", "setup", "--root", str(root), "--dry-run")
    assert res.exit_code == 0, res.output
    assert "create    .mcp.json" in res.output
    assert "nothing written" in res.output
    assert "relate skill install" in res.output and "--global-skill" in res.output  # printed, not run
    assert _tree(root) == before == set()


def test_setup_creates_files_and_selftest_passes(root):
    res = _run("agent", "setup", "--root", str(root), "--yes")
    assert res.exit_code == 0, res.output
    assert "✔ relate get_schema" in res.output
    assert "✔ crosswalk coverage 800-171: 15/97 covered" in res.output
    assert "✖" not in res.output

    cfg = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    servers = cfg["mcpServers"]
    assert set(servers) == {"relate", "crosswalk"}
    store = str((root / "data" / "crosswalk").resolve())
    rl, cw = servers["relate"], servers["crosswalk"]
    assert Path(rl["command"]).is_absolute() and Path(rl["command"]).stem == "relate"
    assert rl["args"] == ["serve", "--mcp", "stdio", "--database", store, "--read-only=live"]
    assert Path(cw["command"]).is_absolute()
    assert cw["env"]["CROSSWALK_STORE"] == store and cw["env"]["DO_NOT_TRACK"] == "1"
    assert rl["type"] == cw["type"] == "stdio"

    for name in S.SKILLS:
        text = (root / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert text == (REPO / "agents" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    manifest = json.loads((root / ".crosswalk-setup.json").read_text(encoding="utf-8"))
    assert ".mcp.json" in manifest["created"] and len(manifest["created"]) == 1 + len(S.SKILLS)
    assert manifest["global_skill"] is None  # relate skill install was not run


def test_undo_removes_exactly_what_was_added(root):
    res = _run("agent", "setup", "--root", str(root), "--yes", "--skip-selftest")
    assert res.exit_code == 0, res.output
    assert _tree(root)
    res = _run("agent", "setup", "--root", str(root), "--undo", "--yes")
    assert res.exit_code == 0, res.output
    assert _tree(root) == set()


def test_undo_restores_an_existing_mcp_json(root):
    original = '{"mcpServers": {"other": {"command": "x"}}}\n'
    (root / ".mcp.json").write_text(original, encoding="utf-8")
    res = _run("agent", "setup", "--root", str(root), "--yes", "--skip-selftest")
    assert res.exit_code == 0, res.output
    merged = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(merged) == {"other", "relate", "crosswalk"}  # the user's own server is kept
    assert (root / ".mcp.json.bak").read_text(encoding="utf-8") == original
    # a second run changes nothing and keeps the first backup
    res = _run("agent", "setup", "--root", str(root), "--yes", "--skip-selftest")
    assert res.exit_code == 0 and "unchanged .mcp.json" in res.output
    assert (root / ".mcp.json.bak").read_text(encoding="utf-8") == original
    res = _run("agent", "setup", "--root", str(root), "--undo", "--yes")
    assert res.exit_code == 0, res.output
    assert (root / ".mcp.json").read_text(encoding="utf-8") == original
    assert _tree(root) == {".mcp.json"}


def test_invalid_existing_mcp_json_is_refused(root):
    (root / ".mcp.json").write_text("{not json", encoding="utf-8")
    res = _run("agent", "setup", "--root", str(root), "--yes", "--skip-selftest")
    assert res.exit_code == 1 and "not valid JSON" in res.output
    assert (root / ".mcp.json").read_text(encoding="utf-8") == "{not json"


def test_cursor_setup_and_undo(root):
    res = _run("agent", "setup", "--root", str(root), "--agent", "cursor", "--yes", "--skip-selftest")
    assert res.exit_code == 0, res.output
    cfg = json.loads((root / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert set(cfg["mcpServers"]) == {"relate", "crosswalk"}
    assert not (root / ".mcp.json").exists()
    rule = (root / ".cursor" / "rules" / "crosswalk-mapper.mdc").read_text(encoding="utf-8")
    assert rule.startswith("---\ndescription: ") and "alwaysApply: false" in rule
    assert _run("agent", "setup", "--root", str(root), "--undo", "--yes").exit_code == 0
    assert _tree(root) == set()


def test_confirmation_declined_writes_nothing(root):
    res = runner.invoke(app, ["agent", "setup", "--root", str(root), "--skip-selftest"], input="n\n")
    assert res.exit_code == 1 and "cancelled" in res.output
    assert _tree(root) == set()


def test_missing_store_gives_a_fix_it_message(tmp_path):
    res = _run("agent", "setup", "--root", str(tmp_path), "--yes")
    assert res.exit_code == 1 and "crosswalk build" in res.output


# --------------------------------------------------------------------------
# the skills themselves
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", S.SKILLS)
def test_skill_files_have_the_hard_rules(name):
    text = (REPO / "agents" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    meta = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", text)
    assert meta and meta.group(1) == name and len(meta.group(2)) > 60
    assert len(text.splitlines()) <= 120
    for needle in ("HARD RULES", "check_claims", "decisions", "path id", "propose_", "✔", "⚠", "✖", "Never send"):
        assert needle in text, f"{name} lacks {needle!r}"


def test_generated_files_are_gitignored():
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (".mcp.json", ".mcp.json.bak", ".crosswalk-setup.json", ".cursor/", ".claude/skills/"):
        assert entry in ignore
    assert "agents/skills/" not in ignore and "agents/" not in ignore


# --------------------------------------------------------------------------
# crosswalk packet AUD-171
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def packet_run(store_copy, tmp_path_factory):
    out = tmp_path_factory.mktemp("packet")
    res = runner.invoke(app, ["packet", "AUD-171", "--out", str(out), "--store", str(store_copy)])
    assert res.exit_code == 0, res.output
    file = out / "out" / "packets" / "AUD-171-2026-12-02.md"
    return res.output, file, file.read_text(encoding="utf-8"), out


def _section(text: str, req: str) -> str:
    m = re.search(rf"^### {re.escape(req)} .*?(?=^### |^## Open items)", text, re.S | re.M)
    assert m, req
    return m.group(0)


def test_packet_has_all_97_requirements(packet_run, store_copy):
    out, file, text, _ = packet_run
    assert "AUD-171: 97 requirements" in out and file.name in out.replace("\\", "/")
    sections = re.findall(r"^### (800-171:\S+) ", text, re.M)
    assert len(sections) == len(set(sections)) == 97
    rows = re.findall(r"^\| (800-171:\S+) \|", text, re.M)
    assert sections == rows
    assert "Scope: 800-171" in text and "Audit date: 2027-01-15" in text
    assert "| Requirements in scope | 97 | 97 |" in text
    # numbers match the oracle (planted scenario S5): 15 direct, 23 inherited, 59 gaps today
    assert "| ✔ Covered directly with valid evidence | 15 | 6 |" in text
    assert "| ⚠ Partial (inherited only or proposed) | 23 | 28 |" in text
    assert "| ✖ Not covered (gap or failed proof) | 59 | 63 |" in text


def test_packet_marks_planted_s1_and_s2(packet_run):
    _, _, text, _ = packet_run
    s1 = _section(text, "800-171:03.05.03")
    assert "### 800-171:03.05.03 Multi-Factor Authentication ✖ / ✖" in s1
    assert "✖ today: EV-044 expired 2026-12-01" in s1
    assert "⚠ today: mapping CTRL-PWP-4 -> 800-171:03.05.03 is proposed (PR-005), not approved" in s1
    assert "P-94fd053fec24" in s1 and "P-1a53bde4375b" in s1
    s2 = _section(text, "800-171:03.03.01")
    assert "### 800-171:03.03.01 Event Logging ✔ / ⚠" in s2  # valid today, only inherited on the audit date
    assert "today ✔ / audit day ✖" in s2 and "✖ on the audit date: EV-100 expired 2026-12-18" in s2
    broken = _section(text, "800-171:03.03.05")  # broken and not inherited
    assert broken.splitlines()[0].endswith("✔ / ✖")  # direct proof valid today, gone on the audit date
    items = text.split("## Open items")[1]
    for needle in ("Renew **EV-044**", "Renew **EV-100**", "Renew **EV-101**", "Renew **EV-102**",
                   "Review proposal **PR-005**", "Gap **03.01.02**"):
        assert needle in items


def test_packet_is_deterministic_and_has_no_gap_hidden(packet_run, store_copy, tmp_path):
    _, file, text, _ = packet_run
    res = runner.invoke(app, ["packet", "AUD-171", "--out", str(tmp_path), "--store", str(store_copy)])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "out" / "packets" / file.name).read_text(encoding="utf-8") == text
    gap = _section(text, "800-171:03.01.02")
    assert "gap: no approved control maps to this requirement" in gap


def test_packet_unknown_audit(store_copy, tmp_path):
    res = runner.invoke(app, ["packet", "AUD-999", "--out", str(tmp_path), "--store", str(store_copy)])
    assert res.exit_code == 1 and "AUD-999" in res.output
