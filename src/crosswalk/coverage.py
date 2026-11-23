"""Run the Q1 coverage query (queries/q1_coverage.cypher) against a built store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import relate

from crosswalk.build import QUERIES_DIR, resolve_store
from crosswalk.sources.nist import natural_key

Q1_PATH = QUERIES_DIR / "q1_coverage.cypher"

FRAMEWORK_ALIASES = {"800-53": "800-53", "800-171": "800-171", "csf": "CSF", "CSF": "CSF"}


def normalise_framework(name: str) -> str:
    return FRAMEWORK_ALIASES.get(name, FRAMEWORK_ALIASES.get(name.lower(), name))


def read_as_of(conn: relate.Connection) -> str:
    rows = conn.execute("MATCH (m:Meta) RETURN toString(m.as_of) AS as_of").fetchall()
    if not rows:
        raise LookupError("the store has no :Meta node; run `crosswalk build` first")
    return rows[0]["as_of"]


def open_read_only(store_dir: str | Path) -> relate.Connection:
    return relate.connect(str(resolve_store(store_dir)), read_only=True)


def _in_baseline(conn: relate.Connection, baseline: str) -> set[str]:
    rows = conn.execute("MATCH (r:Requirement) RETURN r.id AS id, r.baselines AS b").fetchall()
    return {r["id"] for r in rows if baseline in (r["b"] or [])}


def audit_scope(conn: relate.Connection, audit_id: str) -> tuple[str, str | None]:
    """(framework, baseline or None) of an audit, from the Audit node."""
    rows = conn.execute(
        "MATCH (a:Audit {id: $id})-[:SCOPES]->(f:Framework) "
        "RETURN f.id AS framework, a.scope_baseline AS baseline", {"id": audit_id}).fetchall()
    if not rows:
        raise LookupError(f"no audit {audit_id!r}")
    return rows[0]["framework"], rows[0]["baseline"]


def coverage(conn: relate.Connection, framework: str | None = None, as_of: str | None = None,
             audit: str | None = None) -> dict[str, Any]:
    """Return the Q1 result: totals plus per-requirement rows, naturally sorted.

    With ``audit`` the framework and optional baseline come from the audit scope and only
    requirements in that scope are counted.
    """
    baseline = None
    if audit:
        framework, baseline = audit_scope(conn, audit)
    if not framework:
        raise LookupError("give a framework or an audit")
    framework = normalise_framework(framework)
    as_of = as_of or read_as_of(conn)
    rows = conn.execute(Q1_PATH.read_text(encoding="utf-8"),
                        {"framework": framework, "as_of": as_of}).fetchall()
    if not rows:
        raise LookupError(f"no requirements for framework {framework!r}")
    out = dict(rows[0])
    if baseline:
        keep = _in_baseline(conn, baseline)
        reqs = [r for r in out["requirements"] if r["id"] in keep]
        out["requirements"] = reqs
        out["total"] = len(reqs)
        for key, st in (("covered", "covered"), ("inherited", "inherited"), ("gaps", "gap")):
            out[key] = sum(1 for r in reqs if r["status"] == st)
        out["audit"], out["baseline"] = audit, baseline
    elif audit:
        out["audit"] = audit
    out["requirements"] = sorted(out["requirements"], key=lambda r: natural_key(r["id"]))
    for r in out["requirements"]:
        for k in ("controls", "evidence", "via"):
            r[k] = sorted(r[k], key=natural_key)
    return out
