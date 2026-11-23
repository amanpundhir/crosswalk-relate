"""The core Crosswalk questions as Python functions over a read-only Relate connection.

Each function runs one Cypher file from ``queries/`` (all the graph logic lives there, nothing is
re-read from the inputs) and reshapes the rows into plain dicts that mirror ``eval/ground_truth.json``.
Every dict that asserts a fact about coverage, inheritance or evidence carries ``paths``: a list of
``{"id": "P-...", "nodes": [...], "rels": [...]}`` that prove it (see :mod:`crosswalk.paths`).
:func:`check_path` re-runs one such path and says whether it still exists and is still valid.

====  =========================  ===============================================
Q1    :func:`coverage`           q1_coverage.cypher + q1_paths.cypher + q2_adopt.cypher
Q2    :func:`adopt`              q2_adopt.cypher
Q3    :func:`blast`              q3_blast.cypher
Q4    :func:`reuse`              q4_reuse.cypher
Q6    :func:`owner_risk`         q6_owner_risk.cypher
--    :func:`explain`            explain.cypher
--    :func:`proposed_paths`     proposed_paths.cypher
--    :func:`check_path`         check_path.cypher, check_absence.cypher
--    :func:`evidence`           evidence_list.cypher
--    :func:`stale`              stale_tracker.cypher
====  =========================  ===============================================
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any, Iterable

import relate

from crosswalk import coverage as _cov
from crosswalk.build import QUERIES_DIR
from crosswalk.coverage import audit_scope, normalise_framework, read_as_of
from crosswalk.paths import ANY, absence_path, is_absence, make_path, make_paths, path_id, split_node, split_rel
from crosswalk.sources.nist import natural_key

FRAMEWORKS = ["800-53", "800-171", "CSF"]
AFFECTED_AUDIT_RULE = ("audit requests at least one expiring evidence item OR its framework "
                       "contains at least one broken requirement")

__all__ = ["FRAMEWORKS", "adopt", "audit_date", "blast", "check_path", "coverage", "evidence", "explain",
           "owner_risk", "proposed_paths", "resolve_requirement", "reuse", "run", "stale", "path_id", "make_path"]


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _text(name: str) -> str:
    return (QUERIES_DIR / f"{name}.cypher").read_text(encoding="utf-8")


def run(conn: relate.Connection, name: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Run ``queries/<name>.cypher`` and return its rows as plain dicts."""
    return [dict(r) for r in conn.execute(_text(name), params or {}).fetchall()]


def _union(rows: Iterable[dict]) -> dict[str, list[dict]]:
    """Split a (kind, data) tagged-union result into ``{kind: [data, ...]}``."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["kind"], []).append(r["data"])
    return out


def _nk_sorted(items: Iterable[str]) -> list[str]:
    return sorted(items, key=natural_key)


def _fw_sorted(items: Iterable[str]) -> list[str]:
    return sorted(set(items), key=lambda f: FRAMEWORKS.index(f) if f in FRAMEWORKS else len(FRAMEWORKS))


def _as_of(conn: relate.Connection, as_of: str | None) -> str:
    return str(as_of) if as_of else read_as_of(conn)


def audit_date(conn: relate.Connection, audit: str) -> str:
    rows = conn.execute("MATCH (a:Audit {id: $id}) RETURN toString(a.date) AS d", {"id": audit}).fetchall()
    if not rows:
        raise LookupError(f"no audit {audit!r}")
    return rows[0]["d"]


def resolve_requirement(conn: relate.Connection, name: str) -> str:
    """Full requirement id from a full or short id ('03.05.03', 'AC-2(1)', 'GV.OC-01')."""
    name = name.strip()
    cands = [name, name.upper()] + [f"{fw}:{x}" for fw in FRAMEWORKS for x in (name, name.upper())]
    found = {r["id"] for r in conn.execute(
        "MATCH (r:Requirement) WHERE r.id IN $c RETURN r.id AS id", {"c": cands}).fetchall()}
    for c in cands:
        if c in found:
            return c
    raise LookupError(f"no requirement {name!r}")


# --------------------------------------------------------------------------
# Q1 coverage (with receipts)
# --------------------------------------------------------------------------


def coverage(conn: relate.Connection, framework: str | None = None, as_of: str | None = None,
             audit: str | None = None) -> dict:
    """Q1: per-requirement status (covered / inherited / gap) plus the proving ``paths`` of each row.

    Totals and requirement rows come from q1_coverage.cypher (see :func:`crosswalk.coverage.coverage`);
    ``paths`` come from q1_paths.cypher (direct) and q2_adopt.cypher (inherited).
    """
    result = _cov.coverage(conn, framework, as_of, audit)
    fw, at = result["framework"], result["as_of"]
    direct: dict[str, list[dict]] = {}
    for row in run(conn, "q1_paths", {"framework": fw, "as_of": at}):
        direct.setdefault(row["requirement"], []).append(row)
    inherited: dict[str, list[dict]] = {}
    for row in run(conn, "q2_adopt", {"framework": fw, "as_of": at}):
        inherited.setdefault(row["requirement"], []).append(row)
    for r in result["requirements"]:
        rows = direct.get(r["id"], []) if r["status"] == "covered" else (
            inherited.get(r["id"], []) if r["status"] == "inherited" else [])
        r["paths"] = make_paths(rows)
    return result


# --------------------------------------------------------------------------
# Q2 adopt
# --------------------------------------------------------------------------


def adopt(conn: relate.Connection, framework: str, as_of: str | None = None) -> dict:
    """Q2: requirements of ``framework`` already met through a covered 1-hop crosswalk neighbour.

    Shape mirrors ``ground_truth.q2_adopt[framework]``: each inherited item has ``via`` (neighbour ->
    controls -> evidence) and the ``paths`` proving it.
    """
    fw, at = normalise_framework(framework), _as_of(conn, as_of)
    total = conn.execute("MATCH (r:Requirement {framework: $f}) RETURN count(r) AS n", {"f": fw}).fetchall()[0]["n"]
    if not total:
        raise LookupError(f"no requirements for framework {framework!r}")
    by_req: dict[str, dict] = {}
    for row in run(conn, "q2_adopt", {"framework": fw, "as_of": at}):
        item = by_req.setdefault(row["requirement"], {"requirement": row["requirement"], "title": row["title"],
                                                      "_via": {}, "_rows": []})
        item["_rows"].append(row)
        item["_via"].setdefault(row["neighbour"], {}).setdefault(row["control"], set()).add(row["evidence"])
    items = []
    for rid in _nk_sorted(by_req):
        it = by_req[rid]
        via = [{"neighbour": n, "controls": [{"control": c, "evidence": _nk_sorted(evs)}
                                             for c, evs in sorted(ctrls.items(), key=lambda kv: natural_key(kv[0]))]}
               for n, ctrls in sorted(it["_via"].items(), key=lambda kv: natural_key(kv[0]))]
        items.append({"requirement": rid, "title": it["title"], "via": via, "paths": make_paths(it["_rows"])})
    return {"framework": fw, "as_of": at, "active_requirements": total,
            "inherited_count": len(items), "inherited": items}


# --------------------------------------------------------------------------
# Q3 blast radius
# --------------------------------------------------------------------------


def blast(conn: relate.Connection, days: int | None = 30, until: str | None = None,
          audit: str | None = None, as_of: str | None = None) -> dict:
    """Q3: what breaks if evidence expiring in (as_of, cutoff] is not renewed.

    The cutoff is ``until`` if given, else the date of ``audit``, else ``as_of + days``.
    Shape mirrors ``ground_truth.q3_blast_*``; broken rows add ``paths`` (the coverage paths that will
    be lost) and ``inherited_paths`` (what still holds the requirement up through the crosswalk).
    """
    at = _as_of(conn, as_of)
    if audit:
        until = audit_date(conn, audit)
    if until is None:
        until = (dt.date.fromisoformat(at) + dt.timedelta(days=int(days if days is not None else 30))).isoformat()
    until = str(until)
    u = _union(run(conn, "q3_blast", {"as_of": at, "until": until}))

    expiring = []
    for d in sorted(u.get("expiring", []), key=lambda d: natural_key(d["evidence"])):
        expiring.append({
            "evidence": d["evidence"], "expires_at": d["expires_at"],
            "proves": _nk_sorted(d["proves"]),
            "controls_left_without_valid_evidence": _nk_sorted(d["controls_left_without_valid_evidence"]),
            "controls_with_replacement": _nk_sorted(d["controls_with_replacement"]),
            "requested_by": sorted(d["requested_by"]),
            "paths": make_paths(d["paths"]),
        })
    broken = []
    for d in sorted(u.get("broken", []), key=lambda d: natural_key(d["requirement"])):
        broken.append({
            "requirement": d["requirement"], "framework": d["framework"], "title": d["title"],
            "controls_lost": _nk_sorted(d["controls_lost"]),
            "evidence_lost": _nk_sorted(set(d["evidence_lost"])),
            "still_inherited": bool(d["still_inherited"]),
            "inherited_via": _nk_sorted(set(d["inherited_via"])),
            "paths": make_paths(d["paths"]),
            "inherited_paths": make_paths(d["inherited_paths"]),
        })
    by_fw = {fw: [b["requirement"] for b in broken if b["framework"] == fw] for fw in FRAMEWORKS}
    d_as_of = dt.date.fromisoformat(at)
    audits = []
    for d in sorted(u.get("audit", []), key=lambda d: d["audit"]):
        if not d["affected"]:
            continue
        reasons = []
        if d["requests_expiring_evidence"]:
            reasons.append("requests expiring evidence")
        if d["broken_requirements_in_framework"]:
            reasons.append("framework has broken requirements")
        audits.append({
            "audit": d["audit"], "name": d["name"], "framework": d["framework"], "date": d["date"],
            "days_after_as_of": (dt.date.fromisoformat(d["date"]) - d_as_of).days,
            "requests_expiring_evidence": _nk_sorted(d["requests_expiring_evidence"]),
            "broken_requirements_in_framework": d["broken_requirements_in_framework"],
            "reasons": reasons,
            "paths": make_paths(d["paths"]),
        })
    return {
        "as_of": at, "cutoff": until,
        "window_days": (dt.date.fromisoformat(until) - d_as_of).days,
        "affected_audit_rule": AFFECTED_AUDIT_RULE,
        "expiring_evidence": expiring,
        "controls_left_without_valid_evidence": _nk_sorted(d["control"] for d in u.get("control_left", [])),
        "broken_requirements": broken,
        "broken_by_framework": by_fw,
        "broken_counts": {fw: len(v) for fw, v in by_fw.items()},
        "broken_and_not_inherited": [b["requirement"] for b in broken if not b["still_inherited"]],
        "affected_audits": audits,
    }


# --------------------------------------------------------------------------
# Q4 reuse
# --------------------------------------------------------------------------


def reuse(conn: relate.Connection, top: int | None = None, as_of: str | None = None) -> list[dict]:
    """Q4: valid evidence ranked by reuse (direct requirements, frameworks reached, total reach, id).

    Mirrors ``ground_truth.q4_reuse``.  ``paths`` lists Evidence -> Control -> Requirement proofs, plus
    one-hop continuations in ``paths_one_hop``.
    """
    rows = run(conn, "q4_reuse", {"as_of": _as_of(conn, as_of)})
    out = []
    for rank, r in enumerate(rows, 1):  # the Cypher ORDER BY is the ranking
        out.append({
            "rank": rank, "evidence": r["evidence"], "expires_at": r["expires_at"],
            "controls": _nk_sorted(r["controls"]),
            "direct_requirements": sorted(r["direct_requirements"], key=natural_key),
            "direct_count": r["direct_count"],
            "one_hop_requirements": sorted(r["one_hop_requirements"], key=natural_key),
            "reach_count": r["reach_count"],
            "frameworks_direct": _fw_sorted(r["frameworks_direct"]),
            "frameworks_reached": _fw_sorted(r["frameworks_reached"]),
            "framework_count": r["framework_count"],
            "paths": make_paths(r["paths_direct"]),
            "paths_one_hop": make_paths(r["paths_one_hop"]),
        })
    return out[:top] if top else out


# --------------------------------------------------------------------------
# Q6 owner risk
# --------------------------------------------------------------------------


def owner_risk(conn: relate.Connection, as_of: str | None = None) -> dict:
    """Q6: per person, the controls they solely own and what depends on them; plus unowned controls.

    Mirrors ``ground_truth.q6_owner_risk`` and adds ``audits_affected`` (audits scoping the framework
    of a solely-dependent requirement) and ownership/dependency ``paths``.
    """
    u = _union(run(conn, "q6_owner_risk", {"as_of": _as_of(conn, as_of)}))
    dep_by: dict[str, list[dict]] = {}
    for d in u.get("dependent", []):
        dep_by.setdefault(d["person"], []).append(d)
    people = {}
    for d in sorted(u["person"], key=lambda d: d["person"]):
        deps = dep_by.get(d["person"], [])
        mine = _nk_sorted(d["controls_solely_owned"])
        people[d["person"]] = {
            "name": d["name"],
            "controls_solely_owned": mine,
            "sole_owned_count": len(mine),
            "requirements_mapped": sorted(d["requirements_mapped"], key=natural_key),
            "requirements_solely_dependent": sorted((x["requirement"] for x in deps), key=natural_key),
            "systems_touched": sorted(d["systems_touched"]),
            "high_criticality_systems": sorted(d["high_criticality_systems"]),
            "controls_touching_high_systems": _nk_sorted(d["controls_touching_high_systems"]),
            "audits_affected": sorted({a for x in deps for a in x["audits"]}),
            "paths": make_paths(d["paths"]),
            "dependency_paths": make_paths(p for x in deps for p in x["paths"]),
        }
    ranking = [{"person": p, "sole_owned_count": v["sole_owned_count"],
                "controls_touching_high_systems": len(v["controls_touching_high_systems"])}
               for p, v in sorted(people.items(), key=lambda kv: (-kv[1]["sole_owned_count"], kv[0]))
               if v["sole_owned_count"]]
    unowned = sorted(u.get("unowned", []), key=lambda d: natural_key(d["control"]))
    for d in unowned:  # receipt: the control exists, is adopted, and no Person OWNS it
        d["paths"] = [absence_path("Control", d["control"], "OWNS", "Person", reversed_=True)]
    return {"people": people, "unowned_controls": [d["control"] for d in unowned],
            "unowned_detail": unowned, "sole_owner_ranking": ranking}


# --------------------------------------------------------------------------
# Explain
# --------------------------------------------------------------------------


def explain(conn: relate.Connection, requirement: str, as_of: str | None = None) -> dict:
    """Why is ``requirement`` (full id) covered, inherited or a gap?  Paths with dates and validity.

    Shape mirrors ``ground_truth.explain[requirement]``; each entry of ``paths`` also carries its
    path ``id``, ``nodes`` and ``rels`` (re-runnable with :func:`check_path`).
    """
    at = _as_of(conn, as_of)
    u = _union(run(conn, "explain", {"requirement": requirement, "as_of": at}))
    if not u.get("summary"):
        raise LookupError(f"no requirement {requirement!r}")
    summary = u["summary"][0]
    paths = []
    for d in sorted(u.get("path", []), key=lambda d: (natural_key(d["control"]), natural_key(d["evidence"] or ""))):
        p = make_path(d["nodes"], d["rels"])
        row = {"control": d["control"], "control_title": d["control_title"], "control_status": d["control_status"],
               "control_owners": sorted(d["control_owners"]),
               "mapping_approved_by": d["mapping_approved_by"], "mapping_approved_at": d["mapping_approved_at"],
               "evidence": d["evidence"], "valid": bool(d["valid"]),
               "path_id": p["id"], "nodes": p["nodes"], "rels": p["rels"]}
        if d["evidence"] is not None:
            row.update({"evidence_kind": d["evidence_kind"], "evidence_owners": sorted(d["evidence_owners"]),
                        "collected_at": d["collected_at"], "expires_at": d["expires_at"]})
        paths.append(row)
    inh_rows = u.get("inherited", [])
    inherited_paths = [dict(make_path(d["nodes"], d["rels"]), neighbour=d["neighbour"], control=d["control"],
                            evidence=d["evidence"], expires_at=d["expires_at"]) for d in inh_rows]
    inherited_paths.sort(key=lambda p: p["id"])
    proposals = sorted(u.get("proposal", []), key=lambda d: d["proposal"])
    for d in proposals:  # a proposal is citable too: Requirement <-TARGET- Proposal -ABOUT-> Control
        p = make_path([f"Requirement:{requirement}", f"Proposal:{d['proposal']}", f"Control:{d['control']}"],
                      ["TARGET<-", "ABOUT"])
        d.update({"path_id": p["id"], "nodes": p["nodes"], "rels": p["rels"]})
    return {
        "requirement": summary["requirement"], "framework": summary["framework"], "title": summary["title"],
        "as_of": at,
        "covered_direct": summary["direct_valid_paths"] > 0,
        "inherited": bool(inh_rows),
        "inherited_via": _nk_sorted({d["neighbour"] for d in inh_rows}),
        "paths": paths,
        "inherited_paths": inherited_paths,
        "proposed_only": _nk_sorted(d["control"] for d in proposals if d["status"] != "approved"),
        "proposals": proposals,
        "proposed_paths": [{"id": d["path_id"], "nodes": d["nodes"], "rels": d["rels"], "proposal": d["proposal"],
                            "control": d["control"]} for d in proposals if d["status"] == "pending"],
    }


def proposed_paths(conn: relate.Connection, requirement: str | None = None, control: str | None = None,
                   status: str | None = "pending") -> list[dict]:
    """Mapping proposals as citable paths (``Requirement <-TARGET- Proposal -ABOUT-> Control``).

    Each row has ``path_id``/``nodes``/``rels`` (re-runnable with :func:`check_path`, which reports a
    pending proposal as "proposed, not approved"), the proposal ``status``, who proposed it and any decision.
    Filter by ``requirement`` (full id), ``control`` and ``status`` (default pending; None = all).
    """
    out = []
    for r in run(conn, "proposed_paths", {"requirement": requirement, "control": control, "status": status}):
        p = make_path(r.pop("nodes"), r.pop("rels"))
        out.append({**r, "path_id": p["id"], "nodes": p["nodes"], "rels": p["rels"]})
    return out


# --------------------------------------------------------------------------
# Claim checking
# --------------------------------------------------------------------------


def check_path(conn: relate.Connection, nodes: list[str], rels: list[str], as_of: str | None = None) -> dict:
    """Re-run a cited path: does it exist exactly, and is it valid at ``as_of``?

    ``nodes`` are ``'Label:id'`` references and ``rels`` traversal tokens (``'SATISFIES<-'``), exactly as
    returned in the ``nodes``/``rels`` of every path (see :mod:`crosswalk.paths`).  Valid means: every
    SATISFIES hop approved, every Control adopted, every Evidence ``expires_at > as_of``.  Validity is only
    judged for what is on the path: a claim that something is *covered* must cite a path that ends in
    Evidence (a Requirement-Control path alone says nothing about evidence).
    Returns ``{"path_id", "exists", "valid", "problems", "as_of", "nodes", "rels"}``.
    """
    p = make_path(nodes, rels)  # also validates the shape
    at = _as_of(conn, as_of)
    if any(is_absence(r) for r in p["rels"]):
        return _check_absence(conn, p, at)
    rows = run(conn, "check_path", {"nodes": p["nodes"], "rels": p["rels"], "as_of": at})
    row = rows[0]
    problems = list(dict.fromkeys(row["problems"]))
    return {"path_id": p["id"], "exists": bool(row["exists"]), "valid": bool(row["valid"]),
            "problems": problems, "as_of": at, "nodes": p["nodes"], "rels": p["rels"]}


def _check_absence(conn: relate.Connection, p: dict, at: str) -> dict:
    """A path whose LAST hop is an absence (``NO_OWNS<-``): the hops before it are checked as usual, then the
    last node must exist, be adopted (a Control) and have NO such relationship."""
    nodes, rels = p["nodes"], p["rels"]
    if not is_absence(rels[-1]) or any(is_absence(r) for r in rels[:-1]):
        raise ValueError("an absence hop (NO_<TYPE>) may only be the last hop of a path")
    exists, valid, problems = True, True, []
    if len(rels) > 1:  # the ordinary prefix
        pre = run(conn, "check_path", {"nodes": nodes[:-1], "rels": rels[:-1], "as_of": at})[0]
        exists, valid, problems = bool(pre["exists"]), bool(pre["valid"]), list(pre["problems"])
    a_ref, b_ref = nodes[-2], nodes[-1]
    (a_label, a_id), (b_label, b_id) = split_node(a_ref), split_node(b_ref)
    rel_type, reversed_ = split_rel(rels[-1])
    rel_type = rel_type[len("NO_"):]
    rows = run(conn, "check_absence", {"label": a_label, "id": a_id, "other_label": b_label, "other_id": b_id,
                                       "rel": rel_type, "reversed": reversed_})
    if not rows:
        exists = valid = False
        problems.append(f"{a_ref} does not exist")
    else:
        present = list(rows[0]["present"])
        if present:
            exists = valid = False
            arrow = f"<-{rel_type}-" if reversed_ else f"-{rel_type}->"
            problems.append(f"{a_ref} is not without {rel_type}: {a_ref} {arrow} "
                            + ", ".join(f"{b_label}:{x}" for x in present))
        elif a_label == "Control" and not rows[0]["adopted"]:
            valid = False
            problems.append(f"{a_ref} is not adopted")
    return {"path_id": p["id"], "exists": exists, "valid": valid and exists,
            "problems": list(dict.fromkeys(problems)), "as_of": at, "nodes": nodes, "rels": rels}


# --------------------------------------------------------------------------
# Evidence list (expired / expiring / valid, per audit)
# --------------------------------------------------------------------------

EVIDENCE_STATUSES = ("expired", "expiring", "valid")
_STATUS_ALIASES = {"lapsed": ("expired", "expiring")}  # not valid at the cutoff: already gone or gone by then


def parse_statuses(status: str | Iterable[str] | None) -> tuple[str, ...] | None:
    """``'expired,expiring'`` / ``'lapsed'`` / a list -> a tuple of statuses (``None`` = all)."""
    if status is None or status == "":
        return None
    items = status.split(",") if isinstance(status, str) else list(status)
    out: list[str] = []
    for x in items:
        x = str(x).strip().lower()
        if not x:
            continue
        for y in _STATUS_ALIASES.get(x, (x,)):
            if y not in EVIDENCE_STATUSES:
                raise ValueError(f"unknown evidence status {x!r}; use expired, expiring, valid or lapsed "
                                 f"(expired + expiring), separated by commas")
            if y not in out:
                out.append(y)
    return tuple(out) or None


def evidence(conn: relate.Connection, audit: str | None = None, status: str | Iterable[str] | None = None,
             until: str | None = None, as_of: str | None = None) -> dict:
    """Every evidence item (or the items an audit requests) with dates, status and receipts.

    ``status`` is relative to ``as_of`` and the cutoff: ``expired`` (``expires_at <= as_of``), ``expiring``
    (valid at ``as_of`` but ``expires_at <= cutoff``) or ``valid`` (``expires_at > cutoff``).  The cutoff is
    ``until`` if given, else the date of ``audit``, else ``as_of + 30 days`` (same default as blast).
    ``lapsed`` = ``expired,expiring`` = "will not be valid at the cutoff".  Each row lists its requesting
    audits, the controls it proves, and ``request_paths`` (``Audit -REQUESTS-> Evidence``) and
    ``proves_paths`` (``Evidence -PROVES-> Control``): re-running them with check_path says "EV-044 expired
    2026-12-01" for an expired item.
    """
    at = _as_of(conn, as_of)
    want = parse_statuses(status)
    aud = None
    if audit:
        rows = conn.execute("MATCH (a:Audit {id: $id}) RETURN a.id AS id, a.name AS name, toString(a.date) AS date, "
                            "[(a)-[:SCOPES]->(f:Framework) | f.id][0] AS framework", {"id": audit}).fetchall()
        if not rows:
            raise LookupError(f"no audit {audit!r}")
        aud = dict(rows[0])
    cutoff = str(until) if until else (aud["date"] if aud else
                                       (dt.date.fromisoformat(at) + dt.timedelta(days=30)).isoformat())
    d_at = dt.date.fromisoformat(at)
    d_cut = dt.date.fromisoformat(cutoff)
    out = []
    counts = {"total": 0, "expired": 0, "expiring": 0, "valid": 0}
    for r in run(conn, "evidence_list", {"as_of": at, "until": cutoff}):
        reqs = sorted(r["requested_by"], key=lambda x: x["audit"])
        if aud and aud["id"] not in {x["audit"] for x in reqs}:
            continue
        counts["total"] += 1
        counts[r["status"]] += 1
        if want and r["status"] not in want:
            continue
        ctrls = sorted(r["controls"], key=lambda x: natural_key(x["control"]))
        exp = dt.date.fromisoformat(r["expires_at"])
        out.append({
            "evidence": r["evidence"], "kind": r["kind"], "title": r["title"],
            "collected_at": r["collected_at"], "expires_at": r["expires_at"],
            "status": r["status"], "days_to_expiry": (exp - d_at).days,
            "expired_at_cutoff": exp <= d_cut,
            "owners": sorted(r["owners"]),
            "controls": [x["control"] for x in ctrls],
            "requested_by": [{**x, "expires_before_audit": exp <= dt.date.fromisoformat(x["date"])} for x in reqs],
            "request_paths": make_paths({"nodes": [f"Audit:{x['audit']}", f"Evidence:{r['evidence']}"],
                                         "rels": ["REQUESTS"]} for x in reqs),
            "proves_paths": make_paths({"nodes": [f"Evidence:{r['evidence']}", f"Control:{x['control']}"],
                                        "rels": ["PROVES"]} for x in ctrls),
        })
    out.sort(key=lambda d: natural_key(d["evidence"]))
    return {"as_of": at, "cutoff": cutoff, "audit": aud, "status_filter": list(want) if want else None,
            "rule": ("expired: expires_at <= as_of; expiring: as_of < expires_at <= cutoff; valid: expires_at > cutoff; "
                     "cutoff = --until, else the audit's date, else as_of + 30 days"),
            "counts": counts,
            "shown": len(out), "evidence_ids": [d["evidence"] for d in out], "evidence": out}


# --------------------------------------------------------------------------
# The legacy tracker against the graph ("the spreadsheet says compliant")
# --------------------------------------------------------------------------

STALE_KINDS = ("not_adopted", "no_evidence", "expired_evidence", "unowned", "proposed_only", "unmapped")


def is_compliant_text(text: str | None) -> bool:
    """The tracker's free-text status says Compliant (``'Compliant ?'``)."""
    return (text or "").strip().lower().startswith("compliant")


def stale(conn: relate.Connection, as_of: str | None = None, include_ok: bool = False) -> dict:
    """Controls the legacy tracker marks Compliant whose graph reality differs, each with receipts.

    Per tracker row marked Compliant the graph is checked at ``as_of``; the row is *stale* when it has at
    least one issue: ``not_adopted`` (the control is not adopted), ``no_evidence`` (adopted, nothing proves
    it), ``expired_evidence`` (evidence exists, none valid at as_of), ``unowned`` (adopted, nobody owns it),
    ``proposed_only`` / ``unmapped`` (a requirement the tracker lists has only a pending proposal / no
    approved mapping).  ``no_valid_evidence`` lists the controls with ``not_adopted``, ``no_evidence`` or
    ``expired_evidence``.  Every issue carries ``paths``: a TrackerRow -ABOUT-> Control path (what the
    spreadsheet claims), Evidence -PROVES-> Control paths that fail with "expired", absence receipts
    (``NO_OWNS<-``, ``NO_PROVES<-``, ``NO_SATISFIES``) and proposed paths.  ``include_ok`` also returns the
    consistent rows (``issues`` empty).
    """
    at = _as_of(conn, as_of)
    rows = run(conn, "stale_tracker", {"as_of": at})
    rows.sort(key=lambda r: natural_key(r["control"]))
    out: list[dict] = []
    compliant = 0
    for r in rows:
        if not is_compliant_text(r["status_text"]):
            continue
        compliant += 1
        c = r["control"]
        tracker_path = make_path([f"TrackerRow:{r['tracker']}", f"Control:{c}"], ["ABOUT"])
        issues: list[dict] = []
        ev = sorted(r["evidence"], key=lambda e: natural_key(e["evidence"]))
        valid_ev = [e["evidence"] for e in ev if e["valid"]]
        expired_ev = [e for e in ev if not e["valid"]]
        if not r["adopted"]:
            issues.append({"kind": "not_adopted", "detail": f"{c} is not adopted, so nothing can prove it",
                           "paths": [tracker_path]})
        else:
            if not ev:
                issues.append({"kind": "no_evidence", "detail": f"no evidence proves {c}",
                               "paths": [absence_path("Control", c, "PROVES", "Evidence", reversed_=True)]})
            elif not valid_ev:
                issues.append({"kind": "expired_evidence",
                               "detail": "all evidence expired: " + ", ".join(
                                   f"{e['evidence']} ({e['expires_at']})" for e in expired_ev),
                               "evidence": [e["evidence"] for e in expired_ev],
                               "paths": make_paths({"nodes": [f"Evidence:{e['evidence']}", f"Control:{c}"],
                                                    "rels": ["PROVES"]} for e in expired_ev)})
            if not r["owners"]:
                issues.append({"kind": "unowned", "detail": f"{c} has no owner in the graph"
                                                           + (f" (the tracker says {r['tracker_owner']})"
                                                              if r["tracker_owner"] else ""),
                               "paths": [absence_path("Control", c, "OWNS", "Person", reversed_=True)]})
            approved = set(r["satisfies"])
            pend: dict[str, list[dict]] = {}
            for p in r["proposals"]:
                if p["status"] == "pending" and p["requirement"]:
                    pend.setdefault(p["requirement"], []).append(p)
            proposed = [q for q in r["requirements"] if q not in approved and q in pend]
            unmapped = [q for q in r["requirements"] if q not in approved and q not in pend]
            if proposed:
                issues.append({"kind": "proposed_only",
                               "detail": "the tracker lists requirements that only have a pending proposal: "
                                         + ", ".join(proposed),
                               "requirements": proposed,
                               "paths": make_paths({"nodes": [f"Requirement:{q}", f"Proposal:{p['proposal']}",
                                                              f"Control:{c}"], "rels": ["TARGET<-", "ABOUT"]}
                                                   for q in proposed for p in pend[q])})
            if unmapped:
                issues.append({"kind": "unmapped",
                               "detail": "the tracker lists requirements the control has no approved mapping to: "
                                         + ", ".join(unmapped),
                               "requirements": unmapped,
                               "paths": [absence_path("Control", c, "SATISFIES", "Requirement", q) for q in unmapped]})
        if not issues and not include_ok:
            continue
        out.append({
            "control": c, "title": r["title"],
            "tracker": {"id": r["tracker"], "status": r["status_text"], "owner": r["tracker_owner"],
                        "last_reviewed": r["last_reviewed"], "requirements": r["requirements"]},
            "graph": {"adopted": r["adopted"], "status": r["control_status"], "owners": sorted(r["owners"]),
                      "valid_evidence": valid_ev, "expired_evidence": [e["evidence"] for e in expired_ev],
                      "approved_requirements": sorted(r["satisfies"], key=natural_key)},
            "issues": issues, "issue_kinds": [i["kind"] for i in issues],
            "tracker_path": tracker_path,
        })
    by_issue = {k: [x["control"] for x in out if k in x["issue_kinds"]] for k in STALE_KINDS}
    no_valid = [x["control"] for x in out if set(x["issue_kinds"]) & {"not_adopted", "no_evidence", "expired_evidence"}]
    return {"as_of": at, "tracker_rows": len(rows), "marked_compliant": compliant,
            "stale_count": sum(1 for x in out if x["issues"]),
            "no_valid_evidence": no_valid, "by_issue": {k: v for k, v in by_issue.items() if v},
            "stale": out}
