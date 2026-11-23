"""Pure-Python oracle for Crosswalk (spec section 5). No Relate, no Cypher.

The oracle is the independent reference that the Cypher answers are later
compared against. It loads the normalised NIST requirements and crosswalk
(``crosswalk.sources.nist``), the control library (``crosswalk.sources.comply``)
and the Harbor & Pine company pack (``inputs/company``), then computes the
expected answers with ``as_of`` taken from ``company.yaml`` (never the clock).

Definitions (spec v1.1, section 5)
----------------------------------
* A requirement is COVERED (directly) if some adopted control has an approved
  ``SATISFIES`` mapping to it AND at least one evidence item with
  ``expires_at > as_of`` proves that control.
* For a non-800-53 framework, a requirement is INHERITED if it is not covered
  directly but a 1-hop ``EQUIVALENT_TO`` neighbour (any framework) is covered
  directly. 800-53 itself has no inheritance.
* BLAST RADIUS (Q3) = requirements covered directly now that would LOSE direct
  coverage once the evidence expiring in the window is gone (evidence valid at
  as_of but with ``expires_at <= cutoff``). Each carries ``still_inherited``,
  computed on the post-expiry state (never true for 800-53).
* AFFECTED AUDITS (the one rule used here): an audit is affected if it requests
  at least one of the expiring evidence items OR its framework contains at
  least one broken requirement. The output lists both reasons per audit.
* AUDIT SCOPE: each audit in audits.yaml has ``scope: {framework, baseline?}``. With a
  baseline (AUD-53 -> 800-53 MODERATE) only the baseline's active requirements count; otherwise
  the whole framework.
* REUSE (Q4): per currently valid evidence item, the distinct requirements it
  reaches directly (via the controls it proves) and distinct frameworks it
  reaches directly or through one crosswalk hop. Ranked by distinct direct
  requirements, then frameworks reached, then requirements reached (direct +
  1-hop), then id.

CLI::

    python -I eval/oracle.py            # writes eval/ground_truth.json
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))  # python -I ignores PYTHONPATH

import yaml  # noqa: E402

from crosswalk.sources import comply, nist  # noqa: E402

PACK = REPO / "inputs" / "company"
GROUND_TRUTH = REPO / "eval" / "ground_truth.json"
FRAMEWORKS = ["800-53", "800-171", "CSF"]
F53 = "800-53"
WINDOW_DAYS = 30


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _d(v) -> dt.date:
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


def _y(name: str):
    return yaml.safe_load((PACK / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def world() -> dict:
    """Everything the oracle needs, loaded once."""
    reqs = nist.load_requirements()
    edges, _warns = nist.load_crosswalk()
    lib = comply.load_controls(REPO / "inputs" / "templates" / "comply")
    company = _y("company.yaml")
    adj: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        adj[e["a"]].add(e["b"])
        adj[e["b"]].add(e["a"])
    evidence = {e["id"]: e for e in _y("evidence.yaml")}
    proves: dict[str, list[str]] = defaultdict(list)
    for e in evidence.values():
        for c in e["proves"]:
            proves[c].append(e["id"])
    maps: dict[str, list[dict]] = defaultdict(list)
    for m in _y("mappings.yaml"):
        maps[m["control"]].append(m)
    legacy = []
    with (PACK / "legacy_tracker.csv").open(encoding="utf-8", newline="") as fh:
        legacy = list(csv.DictReader(fh))
    return {
        "as_of": _d(company["as_of"]),
        "company": company,
        "reqs": {r["id"]: r for r in reqs},
        "fw_reqs": {fw: sorted((r["id"] for r in reqs if r["framework"] == fw), key=nist.natural_key)
                    for fw in FRAMEWORKS},
        "edges": edges,
        "adj": {k: sorted(v, key=nist.natural_key) for k, v in adj.items()},
        "library": {c["id"]: c for c in lib},
        "people": {p["id"]: p for p in _y("people.yaml")},
        "systems": {s["id"]: s for s in _y("systems.yaml")},
        "controls": {c["id"]: c for c in _y("controls.yaml")},
        "evidence": evidence,
        "proves": {k: sorted(v) for k, v in proves.items()},
        "audits": {a["id"]: a for a in _y("audits.yaml")},
        "maps": dict(maps),
        "proposals": {p["id"]: p for p in _y("proposals.yaml")},
        "decisions": {d["id"]: d for d in _y("decisions.yaml")},
        "legacy": legacy,
    }


def _nk(s: str):
    return nist.natural_key(s)


def fw_of(req_id: str) -> str:
    return req_id.split(":", 1)[0]


# --------------------------------------------------------------------------
# Coverage primitives
# --------------------------------------------------------------------------


def valid_evidence(at: dt.date | None = None) -> set[str]:
    """Evidence ids with ``expires_at > at`` (default as_of)."""
    w = world()
    at = at or w["as_of"]
    return {i for i, e in w["evidence"].items() if _d(e["expires_at"]) > at}


def control_evidence(at: dt.date | None = None, drop_expiring_by: dt.date | None = None) -> dict[str, list[str]]:
    """Adopted control -> valid evidence ids (those proving it)."""
    w = world()
    ok = valid_evidence(at)
    if drop_expiring_by is not None:
        ok = {i for i in ok if _d(w["evidence"][i]["expires_at"]) > drop_expiring_by}
    out = {}
    for c in w["controls"]:
        ev = [i for i in w["proves"].get(c, []) if i in ok]
        if ev:
            out[c] = sorted(ev)
    return out


def direct_coverage(drop_expiring_by: dt.date | None = None) -> dict[str, list[str]]:
    """Requirement -> sorted adopted controls that cover it directly.

    ``drop_expiring_by`` removes the evidence expiring on or before that date
    (used for the blast-radius post-state).
    """
    w = world()
    ce = control_evidence(drop_expiring_by=drop_expiring_by)
    cov: dict[str, set[str]] = defaultdict(set)
    for c in ce:
        for m in w["maps"].get(c, []):
            if m["requirement"] in w["reqs"]:
                cov[m["requirement"]].add(c)
    return {r: sorted(v) for r, v in cov.items()}


def inherited_via(req: str, covered: dict[str, list[str]]) -> list[str]:
    """1-hop neighbours of ``req`` that are covered directly (none for 800-53)."""
    w = world()
    if fw_of(req) == F53 or req in covered:
        return []
    return [n for n in w["adj"].get(req, []) if n in covered]


def inherited_set(framework: str, covered: dict[str, list[str]]) -> list[str]:
    w = world()
    if framework == F53:
        return []
    return [r for r in w["fw_reqs"][framework] if inherited_via(r, covered)]


# --------------------------------------------------------------------------
# Q1 coverage
# --------------------------------------------------------------------------


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def coverage_for(framework: str, covered: dict[str, list[str]] | None = None,
                 only: set[str] | None = None) -> dict:
    w = world()
    covered = direct_coverage() if covered is None else covered
    reqs = w["fw_reqs"][framework]
    if only is not None:
        reqs = [r for r in reqs if r in only]
    direct = [r for r in reqs if r in covered]
    inh = [r for r in inherited_set(framework, covered) if only is None or r in only]
    gap = [r for r in reqs if r not in set(direct) | set(inh)]
    n = len(reqs)
    return {
        "framework": framework,
        "active_requirements": n,
        "covered_direct": direct,
        "inherited": inh,
        "gap": gap,
        "counts": {"direct": len(direct), "inherited": len(inh), "gap": len(gap)},
        "percent_direct": _pct(len(direct), n),
        "percent_direct_plus_inherited": _pct(len(direct) + len(inh), n),
    }


def q1_coverage() -> dict:
    """Per-framework coverage and per-audit (scope = whole framework) coverage."""
    w = world()
    covered = direct_coverage()
    per_fw = {fw: coverage_for(fw, covered) for fw in FRAMEWORKS}
    audits = {}
    now_valid = valid_evidence()
    for aid, a in sorted(w["audits"].items()):
        date = _d(a["date"])
        at_audit = valid_evidence(date)
        scope = a.get("scope") or {"framework": a["framework"]}
        base = nist.load_baseline(name=scope["baseline"]) if scope.get("baseline") else None
        c = coverage_for(a["framework"], covered, only=base) if base else per_fw[a["framework"]]
        audits[aid] = {
            "framework": a["framework"],
            "date": a["date"],
            "scope": (f"{a['framework']} {scope['baseline']} baseline" if base else "whole framework"),
            "scope_baseline": scope.get("baseline"),
            "scope_requirements": c["active_requirements"],
            "counts": c["counts"],
            "percent_direct": c["percent_direct"],
            "percent_direct_plus_inherited": c["percent_direct_plus_inherited"],
            "requested_evidence": len(a["requests"]),
            "requested_evidence_invalid_at_as_of": sorted(set(a["requests"]) - now_valid),
            "requested_evidence_invalid_at_audit_date": sorted(set(a["requests"]) - at_audit),
        }
    return {"by_framework": per_fw, "by_audit": audits}


# --------------------------------------------------------------------------
# Q2 adopt
# --------------------------------------------------------------------------


def q2_adopt(framework: str) -> dict:
    """Requirements of ``framework`` inherited via a covered 1-hop neighbour."""
    w = world()
    covered = direct_coverage()
    ce = control_evidence()
    items = []
    for r in inherited_set(framework, covered):
        via = []
        for n in inherited_via(r, covered):
            via.append({
                "neighbour": n,
                "controls": [{"control": c, "evidence": ce[c]} for c in covered[n]],
            })
        items.append({"requirement": r, "via": via})
    return {
        "framework": framework,
        "active_requirements": len(w["fw_reqs"][framework]),
        "inherited_count": len(items),
        "inherited": items,
    }


# --------------------------------------------------------------------------
# Q3 blast radius
# --------------------------------------------------------------------------


def blast(window_days: int | None = WINDOW_DAYS, until: dt.date | str | None = None) -> dict:
    """Blast radius of evidence expiring in (as_of, cutoff]; cutoff = as_of+days or ``until``."""
    w = world()
    as_of = w["as_of"]
    cutoff = _d(until) if until is not None else as_of + dt.timedelta(days=window_days)
    now_valid = valid_evidence()
    expiring = sorted(
        (i for i in now_valid if _d(w["evidence"][i]["expires_at"]) <= cutoff),
        key=_nk,
    )
    pre = direct_coverage()
    post = direct_coverage(drop_expiring_by=cutoff)
    ce_pre = control_evidence()
    ce_post = control_evidence(drop_expiring_by=cutoff)

    broken_reqs = sorted((r for r in pre if r not in post), key=_nk)
    broken = []
    for r in broken_reqs:
        via = inherited_via(r, post)
        broken.append({
            "requirement": r,
            "framework": fw_of(r),
            "controls_lost": pre[r],
            "still_inherited": bool(via),
            "inherited_via": via,
        })
    # Requirements that were inherited and stop being so (informational).
    inh_lost = []
    for fw in FRAMEWORKS:
        was = set(inherited_set(fw, pre))
        now = set(inherited_set(fw, post))
        inh_lost += sorted(was - now - set(post), key=_nk)

    controls_without = sorted((c for c in ce_pre if c not in ce_post), key=_nk)
    exp_detail = []
    for i in expiring:
        e = w["evidence"][i]
        exp_detail.append({
            "evidence": i,
            "expires_at": e["expires_at"],
            "proves": sorted(e["proves"], key=_nk),
            "controls_left_without_valid_evidence": sorted(
                (c for c in e["proves"] if c in controls_without), key=_nk),
            "controls_with_replacement": sorted(
                (c for c in e["proves"] if c in ce_post), key=_nk),
            "requested_by": sorted(a for a, v in w["audits"].items() if i in v["requests"]),
        })

    by_fw = {fw: [b["requirement"] for b in broken if b["framework"] == fw] for fw in FRAMEWORKS}
    audits = []
    for aid, a in sorted(w["audits"].items()):
        req_exp = sorted(set(a["requests"]) & set(expiring), key=_nk)
        n_broken = len(by_fw[a["framework"]])
        if req_exp or n_broken:
            audits.append({
                "audit": aid,
                "framework": a["framework"],
                "date": a["date"],
                "days_after_as_of": (_d(a["date"]) - as_of).days,
                "requests_expiring_evidence": req_exp,
                "broken_requirements_in_framework": n_broken,
            })
    return {
        "as_of": as_of.isoformat(),
        "cutoff": cutoff.isoformat(),
        "window_days": (cutoff - as_of).days,
        "affected_audit_rule": ("audit requests at least one expiring evidence item OR its framework "
                                "contains at least one broken requirement"),
        "expiring_evidence": exp_detail,
        "controls_left_without_valid_evidence": controls_without,
        "broken_requirements": broken,
        "broken_by_framework": by_fw,
        "broken_counts": {fw: len(v) for fw, v in by_fw.items()},
        "broken_and_not_inherited": [b["requirement"] for b in broken if not b["still_inherited"]],
        "inherited_requirements_lost": inh_lost,
        "affected_audits": audits,
    }


# --------------------------------------------------------------------------
# Q4 reuse ranking
# --------------------------------------------------------------------------


def q4_reuse() -> list[dict]:
    w = world()
    out = []
    for i in sorted(valid_evidence(), key=_nk):
        e = w["evidence"][i]
        controls = [c for c in e["proves"] if c in w["controls"]]
        direct = sorted({m["requirement"] for c in controls for m in w["maps"].get(c, [])
                         if m["requirement"] in w["reqs"]}, key=_nk)
        hop = sorted({n for r in direct for n in w["adj"].get(r, [])} - set(direct), key=_nk)
        fws_direct = sorted({fw_of(r) for r in direct}, key=FRAMEWORKS.index)
        fws_all = sorted({fw_of(r) for r in direct + hop}, key=FRAMEWORKS.index)
        out.append({
            "evidence": i,
            "controls": sorted(controls, key=_nk),
            "direct_requirements": direct,
            "direct_count": len(direct),
            "one_hop_requirements": hop,
            "reach_count": len(direct) + len(hop),
            "frameworks_direct": fws_direct,
            "frameworks_reached": fws_all,
            "framework_count": len(fws_all),
        })
    out.sort(key=lambda d: (-d["direct_count"], -d["framework_count"], -d["reach_count"], _nk(d["evidence"])))
    for rank, d in enumerate(out, 1):
        d["rank"] = rank
    return out


# --------------------------------------------------------------------------
# Q6 owner risk
# --------------------------------------------------------------------------


def q6_owner_risk() -> dict:
    w = world()
    covered = direct_coverage()
    sole: dict[str, list[str]] = defaultdict(list)
    unowned = []
    for cid, c in w["controls"].items():
        owners = c.get("owners") or []
        if not owners:
            unowned.append(cid)
        elif len(owners) == 1:
            sole[owners[0]].append(cid)
    people = {}
    for pid in sorted(w["people"]):
        mine = sorted(sole.get(pid, []), key=_nk)
        mapped = sorted({m["requirement"] for c in mine for m in w["maps"].get(c, [])
                         if m["requirement"] in w["reqs"]}, key=_nk)
        # requirements whose every valid covering control is solely owned by this person
        at_risk = sorted((r for r in mapped if r in covered and all(c in mine for c in covered[r])), key=_nk)
        systems = sorted({s for c in mine for s in w["controls"][c].get("applies_to", [])})
        high = [s for s in systems if w["systems"][s]["criticality"] == "high"]
        people[pid] = {
            "name": w["people"][pid]["name"],
            "controls_solely_owned": mine,
            "sole_owned_count": len(mine),
            "requirements_mapped": mapped,
            "requirements_solely_dependent": at_risk,
            "systems_touched": systems,
            "high_criticality_systems": high,
            "controls_touching_high_systems": sorted(
                (c for c in mine if any(w["systems"][s]["criticality"] == "high"
                                        for s in w["controls"][c].get("applies_to", []))), key=_nk),
        }
    return {
        "people": people,
        "unowned_controls": sorted(unowned, key=_nk),
        "sole_owner_ranking": [
            {"person": p, "sole_owned_count": people[p]["sole_owned_count"],
             "controls_touching_high_systems": len(people[p]["controls_touching_high_systems"])}
            for p in sorted(people, key=lambda p: (-people[p]["sole_owned_count"], p))
            if people[p]["sole_owned_count"]
        ],
    }


# --------------------------------------------------------------------------
# Explain
# --------------------------------------------------------------------------


def explain(requirement: str) -> dict:
    """requirement <- control <- evidence paths, with dates and validity at as_of."""
    w = world()
    as_of = w["as_of"]
    paths = []
    for cid in sorted(w["controls"], key=_nk):
        for m in w["maps"].get(cid, []):
            if m["requirement"] != requirement:
                continue
            evs = w["proves"].get(cid, [])
            base = {"control": cid, "mapping_approved_by": m["approved_by"], "mapping_approved_at": str(m["approved_at"])}
            if not evs:
                paths.append({**base, "evidence": None, "valid": False})
            for i in evs:
                e = w["evidence"][i]
                paths.append({**base, "evidence": i, "collected_at": e["collected_at"],
                              "expires_at": e["expires_at"], "valid": _d(e["expires_at"]) > as_of})
    covered = direct_coverage()
    via = inherited_via(requirement, covered)
    return {
        "requirement": requirement,
        "covered_direct": requirement in covered,
        "inherited": bool(via),
        "inherited_via": via,
        "paths": paths,
        "proposed_only": sorted(
            p["control"] for p in w["proposals"].values()
            if p["requirement"] == requirement and p["status"] != "approved"),
    }


# --------------------------------------------------------------------------
# Scenario helpers
# --------------------------------------------------------------------------


def decoys() -> list[dict]:
    """Expired evidence whose control still has valid evidence (S6 style)."""
    w = world()
    now = valid_evidence()
    ce = control_evidence()
    out = []
    for i, e in sorted(w["evidence"].items(), key=lambda kv: _nk(kv[0])):
        if i in now:
            continue
        for c in e["proves"]:
            if c in w["controls"] and c in ce:
                out.append({"evidence": i, "expired_at": e["expires_at"], "control": c,
                            "valid_replacements": ce[c]})
    return out


def legacy_stale() -> list[dict]:
    """Legacy tracker rows saying Compliant for controls with no valid evidence."""
    w = world()
    ce = control_evidence()
    out = []
    for row in w["legacy"]:
        if "Compliant" in row["status"] and row["control_id"] not in ce:
            out.append({"control": row["control_id"], "last_reviewed": row["last_reviewed"],
                        "adopted": row["control_id"] in w["controls"]})
    return sorted(out, key=lambda d: _nk(d["control"]))


def evidence_expired_unreplaced() -> list[str]:
    """Adopted controls with evidence on file but none valid at as_of."""
    w = world()
    ce = control_evidence()
    return sorted((c for c in w["controls"] if w["proves"].get(c) and c not in ce), key=_nk)


def proposed_only(requirement: str) -> list[str]:
    """Controls with a non-approved proposal to ``requirement`` and no approved mapping to it."""
    w = world()
    approved = {c for c, ms in w["maps"].items() for m in ms if m["requirement"] == requirement}
    return sorted((p["control"] for p in w["proposals"].values()
                   if p["requirement"] == requirement and p["status"] != "approved"
                   and p["control"] not in approved), key=_nk)


def rejections() -> list[dict]:
    w = world()
    return sorted(
        ({"control": d["control"], "requirement": d["requirement"], "decided_by": d["decided_by"],
          "decided_at": str(d["decided_at"]), "reason": d["reason"]}
         for d in w["decisions"].values() if d["decision"] == "rejected"),
        key=lambda d: (d["decided_at"], d["control"]))


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------


def compute() -> dict:
    w = world()
    covered = direct_coverage()
    explain_ids = sorted(set(w["fw_reqs"]["800-171"]) | set(covered), key=lambda r: (FRAMEWORKS.index(fw_of(r)), _nk(r)))
    return {
        "as_of": w["as_of"].isoformat(),
        "definitions": {
            "covered": "adopted control with approved SATISFIES to the requirement AND evidence with expires_at > as_of",
            "inherited": "non-800-53 requirement not covered directly with a 1-hop EQUIVALENT_TO neighbour covered directly",
            "blast": "requirements covered directly now that lose direct coverage when evidence expiring in (as_of, cutoff] is gone",
            "affected_audit": blast()["affected_audit_rule"],
            "audit_scope": "per-audit scope from audits.yaml (AUD-53: 800-53 MODERATE baseline; others whole framework)",
        },
        "q1_coverage": q1_coverage(),
        "q2_adopt": {fw: q2_adopt(fw) for fw in ("800-171", "CSF")},
        "q3_blast_30d": blast(window_days=WINDOW_DAYS),
        "q3_blast_until_audit": {aid: blast(until=a["date"]) for aid, a in sorted(w["audits"].items())},
        "q4_reuse": q4_reuse(),
        "q6_owner_risk": q6_owner_risk(),
        "explain": {r: explain(r) for r in explain_ids},
        "decoys": decoys(),
        "legacy_stale": legacy_stale(),
        "expired_unreplaced_controls": evidence_expired_unreplaced(),
        "rejections": rejections(),
    }


def render(gt: dict | None = None) -> str:
    gt = compute() if gt is None else gt
    return json.dumps(gt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    text = render()
    with GROUND_TRUTH.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    gt = json.loads(text)
    for fw, c in gt["q1_coverage"]["by_framework"].items():
        print(f"{fw}: direct {c['counts']['direct']} ({c['percent_direct']}%), inherited {c['counts']['inherited']}, "
              f"gap {c['counts']['gap']}, direct+inherited {c['percent_direct_plus_inherited']}%")
    b = gt["q3_blast_30d"]
    print("blast 30d:", b["broken_counts"], "affected:", [a["audit"] for a in b["affected_audits"]])
    print(f"wrote {GROUND_TRUTH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
