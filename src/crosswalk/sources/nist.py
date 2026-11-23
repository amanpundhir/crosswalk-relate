"""NIST source loader: 800-53 Rev5, 800-171 Rev3, CSF 2.0 and their crosswalk.

Pure Python (no Relate). Reads the files in ``inputs/nist/raw`` and returns
plain dicts with normalised ids such as ``800-53:AC-2(1)``.

    python -m crosswalk.sources.nist --summary
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings as _warnings
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = REPO_ROOT / "inputs" / "nist" / "raw"
DEFAULT_WARNINGS_PATH = REPO_ROOT / "out" / "ingest-warnings.txt"

F53, F171, FCSF = "800-53", "800-171", "CSF"

FILE_53 = "NIST_SP-800-53_rev5_catalog.json"
FILE_171 = "NIST_SP800-171_rev3_catalog.json"
FILE_BASELINES = {"MODERATE": "NIST_SP-800-53_rev5_MODERATE-baseline_profile.json"}
FILE_CSF = "NIST_CSF_v2.0_catalog.json"
FILE_CSF_XLSX = "csf2.xlsx"
FILE_OVERLAY = "sp800-171r3-cui-overlay.xlsx"

CSF_REF_53 = "SP 800-53 Rev 5.2.0"
CSF_REF_171 = "SP 800-171 Rev 3"

Dict = dict[str, Any]

_PADDED_53 = re.compile(r"([A-Z]{2})-(\d+)(?:\((\d+)\))?")
_FAMILY_ONLY = re.compile(r"[A-Z]{2}")
_REQ_171 = re.compile(r"\d\d\.\d\d\.\d\d")
_INSERT = re.compile(r"\{\{\s*insert:\s*param,\s*([^\s}]+)\s*\}\}")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_OVERLAY_53 = re.compile(r"([A-Z]{2})-(\d+)-(\d+)-(\d+)")
_OVERLAY_171 = re.compile(r"(\d\d)-(\d\d)-(\d\d)")

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def natural_key(value: str) -> list[Any]:
    """Sort key that orders embedded numbers numerically (AC-2 before AC-10)."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", value)]


def norm_53(raw: str) -> str | None:
    """Normalise ``AC-02(03)`` or ``ac-2.3`` style ids to ``AC-2(3)``; None if malformed."""
    text = raw.strip().upper()
    text = re.sub(r"\.(\d+)$", r"(\1)", text)
    m = _PADDED_53.fullmatch(text)
    if not m:
        return None
    fam, num, enh = m.groups()
    return f"{fam}-{int(num)}" + (f"({int(enh)})" if enh else "")


def _load_json(path: Path) -> Dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)["catalog"]


def _props(node: Dict) -> dict[str, str]:
    """Map prop name -> first value (later duplicates ignored)."""
    out: dict[str, str] = {}
    for p in node.get("props", []):
        out.setdefault(p["name"], p["value"])
    return out


def _is_withdrawn(node: Dict) -> bool:
    return _props(node).get("status") == "withdrawn"


def _walk_params(node: Dict, acc: dict[str, Dict]) -> None:
    """Index every param under ``node`` by id and legacy alt-identifier."""
    for p in node.get("params", []):
        acc[p["id"]] = p
        for prop in p.get("props", []):
            if prop["name"] == "alt-identifier":
                acc.setdefault(prop["value"], p)
    for child in node.get("controls", []):
        _walk_params(child, acc)


# --------------------------------------------------------------------------
# Text rendering
# --------------------------------------------------------------------------


def _render_param(param: Dict | None, params: dict[str, Dict], seen: frozenset[str]) -> str:
    """Render a param as a bracketed label or selection; nested inserts resolved."""
    if param is None:
        return "[organization-defined parameter]"
    if param["id"] in seen:  # defensive: cyclic reference
        return "[organization-defined parameter]"
    seen = seen | {param["id"]}
    if "select" in param:
        sel = param["select"]
        choices = "; ".join(_resolve(c, params, seen) for c in sel.get("choice", []))
        how = sel.get("how-many", "").replace("-", " ")
        head = f"Selection ({how})" if how else "Selection"
        return f"[{head}: {choices}]"
    label = _resolve(param.get("label", "parameter"), params, seen)
    return f"[organization-defined {label}]"


def _resolve(text: str, params: dict[str, Dict], seen: frozenset[str] = frozenset()) -> str:
    """Replace ``{{ insert: param, x }}`` markers with rendered param text."""
    return _INSERT.sub(lambda m: _render_param(params.get(m.group(1)), params, seen), text)


def _plain(text: str) -> str:
    """Strip markdown links and collapse whitespace within a line."""
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _item_label(part: Dict) -> str:
    label = _props(part).get("label", "")
    # 800-171 labels look like SR-03.01.01.c.01; keep only the item suffix.
    label = re.sub(r"^SR-\d\d\.\d\d\.\d\d\.", "", label)
    return label + "." if re.fullmatch(r"[a-z]", label) else label


def _flatten(part: Dict, params: dict[str, Dict]) -> list[str]:
    """Lines for a part: its prose, then its nested items depth-first."""
    lines: list[str] = []
    prose = part.get("prose")
    if prose:
        label = _item_label(part) if part.get("name") == "item" else ""
        line = _plain(_resolve(prose, params))
        lines.append(f"{label} {line}".strip())
    for child in part.get("parts", []):
        lines.extend(_flatten(child, params))
    return lines


def _statement_text(node: Dict, params: dict[str, Dict]) -> str:
    stmt = next((p for p in node.get("parts", []) if p.get("name") == "statement"), None)
    return "\n".join(_flatten(stmt, params)) if stmt else ""


# --------------------------------------------------------------------------
# Catalog loaders: each returns (requirements, families, withdrawn_ids)
# --------------------------------------------------------------------------

Loaded = tuple[list[Dict], list[Dict], set[str]]


def _req(id_: str, fw: str, fam_id: str, fam_title: str, title: str, text: str, **extra: Any) -> Dict:
    return {
        "id": id_,
        "framework": fw,
        "family_id": fam_id,
        "family_title": fam_title,
        "title": title,
        "text": text,
        **extra,
    }


def _norm_53_node(oscal_id: str) -> str:
    return f"{F53}:{norm_53(oscal_id)}"


def _load_53(raw_dir: Path) -> Loaded:
    cat = _load_json(raw_dir / FILE_53)
    params: dict[str, Dict] = {}
    for g in cat["groups"]:
        _walk_params(g, params)
    reqs: list[Dict] = []
    fams: list[Dict] = []
    withdrawn: set[str] = set()
    for g in cat["groups"]:
        fam_id, fam_title = f"{F53}:{g['id'].upper()}", g["title"]
        fams.append({"id": fam_id, "framework": F53, "title": fam_title})

        def visit(ctrl: Dict, parent: str | None) -> None:
            cid = _norm_53_node(ctrl["id"])
            if _is_withdrawn(ctrl):
                withdrawn.add(cid)
            else:
                reqs.append(
                    _req(cid, F53, fam_id, fam_title, ctrl["title"], _statement_text(ctrl, params),
                         is_enhancement=parent is not None, parent_id=parent)
                )
            for sub in ctrl.get("controls", []):
                visit(sub, cid)

        for c in g.get("controls", []):
            visit(c, None)
    return reqs, fams, withdrawn


def _load_171(raw_dir: Path) -> Loaded:
    cat = _load_json(raw_dir / FILE_171)
    reqs: list[Dict] = []
    fams: list[Dict] = []
    withdrawn: set[str] = set()
    for g in cat["groups"]:
        fam_id = f"{F171}:{g['id'].removeprefix('SP_800_171_')}"
        fams.append({"id": fam_id, "framework": F171, "title": g["title"]})
        for c in g.get("controls", []):
            rid = f"{F171}:{c['id'].removeprefix('SP_800_171_')}"
            if _is_withdrawn(c):
                withdrawn.add(rid)
                continue
            params: dict[str, Dict] = {}
            _walk_params(c, params)
            reqs.append(_req(rid, F171, fam_id, g["title"], c["title"], _statement_text(c, params)))
    return reqs, fams, withdrawn


def _csf_examples(node: Dict) -> list[str]:
    return [_plain(p["prose"]) for p in node.get("parts", []) if p.get("class") == "example" and p.get("prose")]


def _load_csf(raw_dir: Path) -> Loaded:
    cat = _load_json(raw_dir / FILE_CSF)
    reqs: list[Dict] = []
    fams: list[Dict] = []
    withdrawn: set[str] = set()
    for func in cat["groups"]:
        for category in func.get("controls", []):
            cat_id = f"{FCSF}:{category['id']}"
            cat_active = not _is_withdrawn(category)
            if cat_active:
                fams.append({"id": cat_id, "framework": FCSF, "title": category["title"]})
            for sub in category.get("controls", []):
                sid = f"{FCSF}:{sub['id']}"
                if _is_withdrawn(sub):
                    withdrawn.add(sid)
                    continue
                text = _statement_text(sub, {})
                reqs.append(
                    _req(sid, FCSF, cat_id, category["title"], text, text, examples=_csf_examples(sub))
                )
    return reqs, fams, withdrawn


def _load_all(raw_dir: Path) -> dict[str, Loaded]:
    raw_dir = Path(raw_dir)
    return {F53: _load_53(raw_dir), F171: _load_171(raw_dir), FCSF: _load_csf(raw_dir)}


def _sorted(items: Iterable[Dict]) -> list[Dict]:
    order = {F53: 0, F171: 1, FCSF: 2}
    return sorted(items, key=lambda d: (order[d["framework"]], natural_key(d["id"])))


# --------------------------------------------------------------------------
# Public: requirements, families, frameworks
# --------------------------------------------------------------------------


def load_requirements(raw_dir: str | Path = DEFAULT_RAW_DIR) -> list[Dict]:
    """All active requirements across the three frameworks, sorted."""
    loaded = _load_all(Path(raw_dir))
    return _sorted(r for reqs, _, _ in loaded.values() for r in reqs)


def load_families(raw_dir: str | Path = DEFAULT_RAW_DIR) -> list[Dict]:
    """Families (800-53 groups, 800-171 groups, CSF categories); withdrawn CSF categories dropped."""
    loaded = _load_all(Path(raw_dir))
    return _sorted(f for _, fams, _ in loaded.values() for f in fams)


def load_frameworks() -> list[Dict]:
    """The three frameworks with name and version."""
    return [
        {"id": F53, "name": "NIST SP 800-53", "version": "Rev 5.2.0"},
        {"id": F171, "name": "NIST SP 800-171", "version": "Rev 3"},
        {"id": FCSF, "name": "NIST Cybersecurity Framework", "version": "2.0"},
    ]


def load_baseline(raw_dir: str | Path = DEFAULT_RAW_DIR, name: str = "MODERATE") -> set[str]:
    """Normalised ids (``800-53:AC-2(1)``) of the active controls in an 800-53 Rev5 baseline.

    Reads NIST's OSCAL baseline profile (``imports[].include-controls[].with-ids``). Ids that are
    withdrawn or absent from the catalog are dropped, so the result is a subset of the active
    800-53 requirements.
    """
    raw_dir = Path(raw_dir)
    try:
        fname = FILE_BASELINES[name.upper()]
    except KeyError:
        raise ValueError(f"unknown baseline {name!r}; known: {sorted(FILE_BASELINES)}") from None
    with (raw_dir / fname).open(encoding="utf-8") as fh:
        profile = json.load(fh)["profile"]
    ids: set[str] = set()
    for imp in profile.get("imports", []):
        for inc in imp.get("include-controls", []):
            for raw in inc.get("with-ids", []):
                norm = norm_53(raw)
                if norm:
                    ids.add(f"{F53}:{norm}")
    reqs, _, _ = _load_53(raw_dir)
    return ids & {r["id"] for r in reqs}


# --------------------------------------------------------------------------
# Crosswalk
# --------------------------------------------------------------------------


def _sheet_rows(path: Path, sheet: str, header_row: int) -> list[dict[str, Any]]:
    """Rows of a sheet as dicts keyed by stripped header names."""
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")  # openpyxl "no default style"
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(wb[sheet].iter_rows(values_only=True))
    finally:
        wb.close()
    header = [str(h).strip() if h is not None else "" for h in rows[header_row - 1]]
    return [dict(zip(header, r)) for r in rows[header_row:]]


class _Checker:
    """Validates edge endpoints against active ids; collects warnings."""

    def __init__(self, active: set[str], withdrawn: set[str]) -> None:
        self.active, self.withdrawn = active, withdrawn
        self.warnings: set[str] = set()

    def ok(self, node: str, origin: str, context: str) -> bool:
        if node in self.active:
            return True
        kind = "withdrawn-target" if node in self.withdrawn else "unknown-target"
        self.warnings.add(f"{kind}: {node} ({origin}, {context})")
        return False

    def warn(self, kind: str, detail: str) -> None:
        self.warnings.add(f"{kind}: {detail}")


def _csf_edges(raw_dir: Path, chk: _Checker) -> list[Dict]:
    edges: list[Dict] = []
    for row in _sheet_rows(raw_dir / FILE_CSF_XLSX, "CSF 2.0", header_row=2):
        sub = str(row.get("Subcategory") or "")
        if not sub or "[Withdrawn" in sub:
            continue
        sub_id = f"{FCSF}:{sub.split(':')[0].strip()}"
        refs = str(row.get("Informative References") or "")
        for line in refs.split("\n"):
            source, _, value = line.partition(": ")
            value = value.strip()
            if source == CSF_REF_53:
                edges.extend(_csf_to_53(sub_id, value, chk))
            elif source == CSF_REF_171:
                edges.extend(_csf_to_171(sub_id, value, chk))
    return edges


def _csf_to_53(sub_id: str, value: str, chk: _Checker) -> list[Dict]:
    if _FAMILY_ONLY.fullmatch(value):
        chk.warn("family-code", f"{sub_id} -> {value} (csf2.xlsx, bare 800-53 family code)")
        return []
    norm = norm_53(value)
    if norm is None:
        chk.warn("malformed-id", f"{sub_id} -> {value!r} (csf2.xlsx, 800-53 reference)")
        return []
    target = f"{F53}:{norm}"
    if chk.ok(sub_id, "csf2.xlsx", "CSF subcategory") and chk.ok(target, "csf2.xlsx", f"from {sub_id}"):
        return [{"a": sub_id, "b": target, "source": "csf2.xlsx", "kind": "informative-reference"}]
    return []


def _csf_to_171(sub_id: str, value: str, chk: _Checker) -> list[Dict]:
    if not _REQ_171.fullmatch(value):
        chk.warn("malformed-id", f"{sub_id} -> {value!r} (csf2.xlsx, 800-171 reference)")
        return []
    target = f"{F171}:{value}"
    if chk.ok(sub_id, "csf2.xlsx", "CSF subcategory") and chk.ok(target, "csf2.xlsx", f"from {sub_id}"):
        return [{"a": sub_id, "b": target, "source": "csf2.xlsx", "kind": "informative-reference"}]
    return []


def _overlay_pairs(raw_dir: Path, chk: _Checker) -> set[tuple[str, str]]:
    """(171 requirement, 53 control) pairs from CUI rows of the overlay."""
    pairs: set[tuple[str, str]] = set()
    for row in _sheet_rows(raw_dir / FILE_OVERLAY, "CUI Overlay", header_row=1):
        if str(row.get("Tailoring Decision") or "").strip() != "CUI":
            continue
        m171 = _OVERLAY_171.match(str(row.get("Unique Sort ID (800-171r3)") or "").strip())
        if not m171:
            continue
        sort53 = str(row.get("Unique Sort ID (800-53r5)") or "").strip()
        m53 = _OVERLAY_53.fullmatch(sort53)
        if not m53:
            chk.warn("malformed-id", f"{sort53!r} (overlay, 800-53 sort id)")
            continue
        fam, num, enh, _item = m53.groups()
        ctrl = f"{F53}:{fam}-{int(num)}" + (f"({int(enh)})" if int(enh) else "")
        pairs.add((f"{F171}:{'.'.join(m171.groups())}", ctrl))
    return pairs


def _oscal_pairs(raw_dir: Path) -> set[tuple[str, str]]:
    """(171 requirement, 53 control) pairs from OSCAL reference links."""
    cat = _load_json(raw_dir / FILE_171)
    by_uuid = {r["uuid"]: r["title"] for r in cat.get("back-matter", {}).get("resources", [])}
    pairs: set[tuple[str, str]] = set()
    for g in cat["groups"]:
        for c in g.get("controls", []):
            if _is_withdrawn(c):
                continue
            req = f"{F171}:{c['id'].removeprefix('SP_800_171_')}"
            for link in c.get("links", []):
                title = by_uuid.get(link["href"].lstrip("#"), "")
                norm = norm_53(title) if re.fullmatch(r"[A-Z]{2}-\d\d(\(\d\d\))?", title) else None
                if norm:
                    pairs.add((req, f"{F53}:{norm}"))
    return pairs


def _derived_edges(raw_dir: Path, chk: _Checker) -> list[Dict]:
    overlay = _overlay_pairs(raw_dir, chk)
    oscal = _oscal_pairs(raw_dir)
    edges: list[Dict] = []
    for a, b in sorted(overlay | oscal):
        in_o, in_s = (a, b) in overlay, (a, b) in oscal
        source = "both" if in_o and in_s else ("overlay" if in_o else "oscal")
        if chk.ok(a, source, "800-171 requirement") and chk.ok(b, source, f"from {a}"):
            edges.append({"a": a, "b": b, "source": source, "kind": "derived-from"})
    return edges


def _dedupe(edges: Iterable[Dict]) -> list[Dict]:
    """Keep one edge per (unordered pair, kind)."""
    seen: dict[tuple[frozenset[str], str], Dict] = {}
    for e in edges:
        seen.setdefault((frozenset((e["a"], e["b"])), e["kind"]), e)
    return sorted(seen.values(), key=lambda e: (e["kind"], natural_key(e["a"]), natural_key(e["b"])))


def load_crosswalk(raw_dir: str | Path = DEFAULT_RAW_DIR) -> tuple[list[Dict], list[str]]:
    """Return ``(edges, warnings)``; edges between non-active endpoints are dropped."""
    raw_dir = Path(raw_dir)
    loaded = _load_all(raw_dir)
    active = {r["id"] for reqs, _, _ in loaded.values() for r in reqs}
    withdrawn = set().union(*(w for _, _, w in loaded.values()))
    chk = _Checker(active, withdrawn)
    edges = _dedupe(_csf_edges(raw_dir, chk) + _derived_edges(raw_dir, chk))
    return edges, sorted(chk.warnings)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _summary_lines(reqs: list[Dict], edges: list[Dict], warns: list[str]) -> list[str]:
    lines = ["Requirements:"]
    for fw in (F53, F171, FCSF):
        mine = [r for r in reqs if r["framework"] == fw]
        extra = ""
        if fw == F53:
            enh = sum(1 for r in mine if r["is_enhancement"])
            extra = f" (base {len(mine) - enh}, enhancements {enh})"
        lines.append(f"  {fw}: {len(mine)}{extra}")
    lines.append("Edges by kind/source:")
    for (kind, source), n in sorted(Counter((e["kind"], e["source"]) for e in edges).items()):
        lines.append(f"  {kind} / {source}: {n}")
    lines.append(f"  total: {len(edges)}")
    lines.append("Warnings by type:")
    for kind, n in sorted(Counter(w.split(":")[0] for w in warns).items()):
        lines.append(f"  {kind}: {n}")
    lines.append(f"  total: {len(warns)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summary", action="store_true", help="print counts and write warnings file")
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    ap.add_argument("--warnings-out", type=Path, default=DEFAULT_WARNINGS_PATH)
    args = ap.parse_args(argv)
    if not args.summary:
        ap.print_help()
        return 0
    reqs = load_requirements(args.raw_dir)
    edges, warns = load_crosswalk(args.raw_dir)
    args.warnings_out.parent.mkdir(parents=True, exist_ok=True)
    args.warnings_out.write_text("\n".join(warns) + ("\n" if warns else ""), encoding="utf-8")
    print("\n".join(_summary_lines(reqs, edges, warns)))
    print(f"Warnings written to {args.warnings_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
