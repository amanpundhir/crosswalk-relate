"""Deterministic control splitter for the StrongDM comply policy templates.

Implements spec section 2 (docs/spec/company-pack-spec.md):

* Skip the Purpose, Scope, Background, References and Appendix sections.
* A control is every ``i.`` item with its ``1.`` children folded in (joined
  with `` | ``), plus every ``a.`` item that has no children.
* Ids are ``CTRL-<ACRONYM>-<n>`` in file order, starting at 1.

The input files are data. They are only read as text, never executed.

CLI::

    python -m crosswalk.sources.comply --dump [--templates DIR] [--out FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_TEMPLATES = Path("inputs/templates/comply")
DEFAULT_OUT = Path("out/control_library.json")

# Section headings (H1) whose items are not controls.
SKIP_SECTION = re.compile(
    r"purpose|scope|background|references|appendix|appendices|overview|coming soon",
    re.I,
)
_HEADING = re.compile(r"^#\s*([^#].*?)\s*$")
_ITEM = re.compile(r"^\s*([a-z]|[ivx]+|\d+)\.\s+(.*\S)\s*$")
_FRONT_ACRONYM = re.compile(r"^acronym:\s*(.+?)\s*$", re.M)
_FRONT_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.M)

_XREF = re.compile(
    r"\b(is|are) (defined|described|outlined|listed|documented|specified) (in|by)\b"
    r"|\(reference \(|^(see|refer to)\b",
    re.I,
)
_CAPTION = re.compile(r"^(table|figure)\s+\d+", re.I)


def _level(marker: str) -> int:
    if marker == "a":
        return 1
    if marker == "i":
        return 2
    if marker.isdigit():
        return 3
    return 0


def strip_markdown(s: str) -> str:
    """Remove markdown emphasis, code ticks and links; collapse whitespace."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
    s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", s)
    s = s.replace("`", "").replace("\\", "")
    return re.sub(r"\s+", " ", s).strip()


def _title(text: str) -> str:
    t = text.split(" | ")[0]
    if len(t) <= 80:
        return t.rstrip(" .:;,")
    cut = t[:80]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" .:;,") + "..."


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def is_vague(text: str, has_children_pipe: bool) -> bool:
    """Heuristic from the templates profile.

    Vague = under 8 words, cross-reference only, a table/figure caption, or a
    dangling stem (ends with a colon and has no folded children).
    """
    if len(text.split()) < 8:
        return True
    if _XREF.search(text):
        return True
    if _CAPTION.match(text):
        return True
    if text.rstrip().endswith(":") and not has_children_pipe:
        return True
    return False


def _parse_policy(path: Path) -> tuple[str, str, list[dict]]:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    head, _, body = raw.partition("\n---\n")
    acronym = _FRONT_ACRONYM.search(head).group(1).strip().strip("'\"")
    name_m = _FRONT_NAME.search(head)
    name = name_m.group(1).strip() if name_m else acronym

    items: list[dict] = []
    section = ""
    cur: dict | None = None
    for line in body.split("\n"):
        h = _HEADING.match(line)
        if h:
            section = h.group(1).strip()
            cur = None
            continue
        m = _ITEM.match(line)
        if m:
            lvl = _level(m.group(1))
            if lvl:
                cur = {"section": section, "level": lvl, "text": m.group(2).strip()}
                items.append(cur)
                continue
        s = line.strip()
        if s and cur is not None and not s.startswith("\\"):
            cur["text"] += " " + s
    return acronym, name, items


def _split_items(items: list[dict]) -> list[dict]:
    """Apply the split rule. Returns dicts with raw text and context."""
    out: list[dict] = []
    ctx1 = ""
    for i, it in enumerate(items):
        if SKIP_SECTION.search(it["section"]):
            continue
        if it["level"] == 1:
            ctx1 = it["text"]
            nxt = items[i + 1] if i + 1 < len(items) else None
            if nxt and nxt["level"] > 1 and not SKIP_SECTION.search(nxt["section"]):
                continue  # heading-like parent, not a control
            out.append({"section": it["section"], "text": it["text"], "context": "",
                        "children": 0})
        elif it["level"] == 2:
            txt = it["text"]
            kids = 0
            j = i + 1
            while j < len(items) and items[j]["level"] == 3:
                txt += " | " + items[j]["text"]
                kids += 1
                j += 1
            out.append({"section": it["section"], "text": txt, "context": ctx1,
                        "children": kids})
        # level 3 items are folded into their level-2 parent
    return out


def load_controls(templates_dir: str | Path = DEFAULT_TEMPLATES) -> list[dict]:
    """Return the control library, deterministic in policy-file name order."""
    base = Path(templates_dir)
    pol_dir = base / "policies" if (base / "policies").is_dir() else base
    controls: list[dict] = []
    for f in sorted(pol_dir.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        acronym, name, items = _parse_policy(f)
        for n, c in enumerate(_split_items(items), start=1):
            text = strip_markdown(c["text"])
            controls.append({
                "id": f"CTRL-{acronym}-{n}",
                "policy": acronym,
                "policy_name": name,
                "policy_file": f.name,
                "title": _title(text),
                "text": text,
                "context": strip_markdown(c["context"]),
                "text_sha": text_sha(text),
                "vague": is_vague(text, c["children"] > 0),
            })
    return controls


def dump(templates_dir: str | Path = DEFAULT_TEMPLATES,
         out: str | Path = DEFAULT_OUT) -> list[dict]:
    controls = load_controls(templates_dir)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(controls, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return controls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dump", action="store_true", help="write the library JSON")
    ap.add_argument("--templates", default=str(DEFAULT_TEMPLATES))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    controls = dump(args.templates, args.out) if args.dump else load_controls(args.templates)
    vague = sum(1 for c in controls if c["vague"])
    print(f"{len(controls)} controls ({vague} vague)"
          + (f" -> {args.out}" if args.dump else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
