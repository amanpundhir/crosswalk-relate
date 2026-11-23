"""The auditor packet: ``crosswalk packet AUD-171`` (deterministic, no LLM).

For every requirement in an audit's scope it collects, with :func:`crosswalk.queries.explain`, the control, the
evidence with its dates and the owner, turns each fact into a *claim that cites a path id*, and re-runs every
claim with :func:`crosswalk.claims.check_claims` **twice**: as of the store's date (today) and as of the audit
date (what the auditor will see).  Nothing is hidden: a failing line stays in the packet with its symbol and
reason.  The packet is Markdown: a summary table, one section per requirement and a list of open items.

Requirement symbol (per date):

* ``✔`` at least one direct (approved mapping, valid evidence) claim re-ran valid;
* ``⚠`` no direct proof, but a crosswalk-inherited claim is valid, or a mapping is only proposed;
* ``✖`` nothing valid: a gap, or every cited path failed (expired evidence, ...).

A gap has no path to cite, so it is reported as ``✖ gap`` without a claim.  The output has no clock in it:
the same store gives byte-identical Markdown.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import relate

from crosswalk import claims as C
from crosswalk import queries as Q
from crosswalk.coverage import read_as_of

OK, WARN, FAIL = "✔", "⚠", "✖"
_EXPIRED = re.compile(r"(\S+) expired (\d{4}-\d{2}-\d{2})")
MAX_INHERITED = 3  # inherited claims shown per requirement (best path per neighbour/control)


def _short(rid: str) -> str:
    return rid.split(":", 1)[-1]


def _people(conn: relate.Connection) -> dict[str, str]:
    return {r["id"]: r["n"] for r in conn.execute("MATCH (p:Person) RETURN p.id AS id, p.name AS n").fetchall()}


def _claims_for(rid: str, title: str, exps: list[dict]) -> list[dict]:
    """Claims about one requirement, built from its explain() results (union over the dates)."""
    out: list[dict] = []
    seen: set[str] = set()
    for exp in exps:
        for p in exp["paths"]:
            if p["path_id"] in seen:
                continue
            seen.add(p["path_id"])
            if p["evidence"]:
                text = (f"{rid} is satisfied by {p['control']} and proven by {p['evidence']} "
                        f"(collected {p.get('collected_at')}, expires {p.get('expires_at')})")
            else:
                text = f"{rid} is satisfied by {p['control']}, which has no evidence"
            out.append({"text": text, "kind": "coverage", "path_ids": [p["path_id"]], "role": "direct",
                        "control": p["control"], "evidence": p["evidence"]})
    best: dict[tuple, dict] = {}
    for exp in exps:
        for p in exp["inherited_paths"]:
            key = (p["neighbour"], p["control"])
            if key not in best or (p["expires_at"] or "") > (best[key]["expires_at"] or ""):
                best[key] = p
    for (nb, ctrl), p in sorted(best.items(), key=lambda kv: (kv[1]["expires_at"] or "", kv[0]), reverse=True)[:MAX_INHERITED]:
        out.append({"text": f"{rid} is met through the crosswalk neighbour {nb}: {ctrl} proven by {p['evidence']} "
                            f"(expires {p['expires_at']})",
                    "kind": "coverage", "path_ids": [p["id"]], "role": "inherited", "control": ctrl,
                    "evidence": p["evidence"], "neighbour": nb})
    for exp in exps:
        for d in exp["proposals"]:
            if d["status"] != "pending" or d["path_id"] in seen:
                continue
            seen.add(d["path_id"])
            out.append({"text": f"{d['control']} is proposed for {rid} ({d['proposal']}), pending human approval",
                        "kind": "proposal", "path_ids": [d["path_id"]], "role": "proposal",
                        "control": d["control"], "proposal": d["proposal"]})
    return out


def _symbol(claims: list[dict], date_key: str, has_paths: bool) -> tuple[str, str]:
    """(symbol, short reason) of a requirement at one date, from its checked claims."""
    if not claims or not has_paths:
        return FAIL, "gap: no approved control maps to this requirement"
    direct = [c for c in claims if c["role"] == "direct"]
    if any(c[date_key]["verdict"] == "verified" for c in direct):
        return OK, "approved mapping with valid evidence"
    inh = [c for c in claims if c["role"] == "inherited" and c[date_key]["verdict"] == "verified"]
    why = []
    for c in direct:
        why.append(f"{c['control']}: " + (c[date_key]["reason"] if c[date_key]["verdict"] != "verified" else "valid"))
    if inh:
        nbs = sorted({c["neighbour"] for c in inh})
        return WARN, "no valid direct proof" + (f" ({'; '.join(why)})" if why else "") + f"; met only through {', '.join(nbs)}"
    props = [c for c in claims if c["role"] == "proposal"]
    if props and not direct:
        return WARN, "only proposed mappings: " + ", ".join(c["proposal"] for c in props) + " pending approval"
    if props:
        return FAIL, "; ".join(why) + "; proposal " + ", ".join(c["proposal"] for c in props) + " pending approval"
    return FAIL, "; ".join(why) or "no valid proof"


def build_packet(conn: relate.Connection, audit: str, as_of: str | None = None) -> dict[str, Any]:
    """Collect and check everything the packet shows.  Read-only."""
    from crosswalk import coverage as cov

    rows = conn.execute("MATCH (a:Audit {id: $id}) RETURN a.id AS id, a.name AS name, toString(a.date) AS date",
                        {"id": audit}).fetchall()
    if not rows:
        raise LookupError(f"no audit {audit!r}")
    a = rows[0]
    framework, baseline = cov.audit_scope(conn, audit)
    today = as_of or read_as_of(conn)
    audit_date = a["date"]
    reqs = Q.coverage(conn, None, today, audit)["requirements"]
    reqs.sort(key=lambda r: Q.natural_key(r["id"]))
    people = _people(conn)
    registry = C.PathRegistry()
    registry.discovered = True  # every path we cite comes from explain(): never run the global discovery

    reqrows: list[dict] = []
    all_claims: list[dict] = []
    for r in reqs:
        exps = [Q.explain(conn, r["id"], d) for d in (today, audit_date)]
        for e in exps:
            registry.register_result(e, "packet")
        claims = _claims_for(r["id"], r["title"], exps)
        has_paths = bool(claims)
        reqrows.append({"id": r["id"], "title": r["title"], "family": r["family_title"], "claims": claims,
                        "has_paths": has_paths, "paths": exps[1]["paths"], "today_paths": exps[0]["paths"],
                        "proposals": [d for d in exps[0]["proposals"] if d["status"] == "pending"]})
        all_claims += claims

    checked: dict[str, dict] = {}
    for key, date in (("today", today), ("audit", audit_date)):
        answer = {"question": f"Auditor packet for {audit}", "agent": "packet",
                  "claims": [{"text": c["text"], "kind": c["kind"], "path_ids": c["path_ids"]} for c in all_claims]}
        checked[key] = C.check_claims(conn, answer, registry, date)
        for c, v in zip(all_claims, checked[key]["claims"]):
            c[key] = v
    for row in reqrows:
        for key in ("today", "audit"):
            row[f"{key}_symbol"], row[f"{key}_reason"] = _symbol(row["claims"], key, row["has_paths"])
        ctrls = sorted({c["control"] for c in row["claims"] if c["role"] == "direct"}, key=Q.natural_key)
        row["controls"] = ctrls
    return {"audit": audit, "name": a["name"], "audit_date": audit_date, "as_of": today, "framework": framework,
            "baseline": baseline, "requirements": reqrows, "checked": checked, "people": people,
            "total": len(reqrows)}


# --------------------------------------------------------------------------
# open items
# --------------------------------------------------------------------------


def open_items(packet: dict) -> list[str]:
    """Markdown bullets: what a human must still do, derived only from failing or partial claims."""
    people, items = packet["people"], []
    renew: dict[str, dict] = {}
    review: dict[str, dict] = {}
    gaps: list[dict] = []
    ownerless: dict[str, list[str]] = {}
    for row in packet["requirements"]:
        if not row["has_paths"]:
            gaps.append(row)
        for c in row["claims"]:
            for key in ("today", "audit"):
                v = c[key]
                for p in v["paths"]:
                    for prob in p.get("problems", []):
                        m = _EXPIRED.search(prob)
                        if m:
                            d = renew.setdefault(m.group(1), {"date": m.group(2), "reqs": set(), "owners": set()})
                            d["reqs"].add(row["id"])
            if c["role"] == "proposal":
                d = review.setdefault(c["proposal"], {"control": c["control"], "reqs": set()})
                d["reqs"].add(row["id"])
        for p in row["today_paths"]:
            if not p["control_owners"]:
                ownerless.setdefault(p["control"], []).append(row["id"])
    # owner names for evidence from explain paths
    ev_owner: dict[str, set] = {}
    for row in packet["requirements"]:
        for p in row["today_paths"] + row["paths"]:
            if p["evidence"]:
                ev_owner.setdefault(p["evidence"], set()).update(p.get("evidence_owners", []))
    for ev in sorted(renew, key=Q.natural_key):
        d = renew[ev]
        who = ", ".join(sorted(people.get(o, o) for o in ev_owner.get(ev, ()))) or "no owner on record"
        reqs = ", ".join(sorted(map(_short, d["reqs"])))
        items.append(f"- ✖ Renew **{ev}** (expires {d['date']}, owner {who}): breaks direct proof for {reqs}.")
    for pr in sorted(review, key=Q.natural_key):
        d = review[pr]
        reqs = ", ".join(sorted(map(_short, d["reqs"])))
        items.append(f"- ⚠ Review proposal **{pr}** ({d['control']} for {reqs}): a proposed mapping is not coverage until a human approves it.")
    for ctrl in sorted(ownerless, key=Q.natural_key):
        items.append(f"- ⚠ Control **{ctrl}** has no owner (proves {', '.join(sorted(set(map(_short, ownerless[ctrl]))))}).")
    inh_only = [r for r in packet["requirements"] if r["audit_symbol"] == WARN and not r["proposals"]]
    if inh_only:
        items.append(f"- ⚠ {len(inh_only)} requirement(s) have no valid direct proof on the audit date and are met only through the NIST crosswalk: "
                     + ", ".join(_short(r["id"]) for r in inh_only) + ".")
    for g in gaps:
        items.append(f"- ✖ Gap **{_short(g['id'])}** {g['title']}: no approved control maps to it.")
    return items


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(packet: dict) -> str:
    rows, today, adate = packet["requirements"], packet["as_of"], packet["audit_date"]
    people = packet["people"]
    count = lambda key, sym: sum(1 for r in rows if r[f"{key}_symbol"] == sym)  # noqa: E731
    scope = packet["framework"] + (f", {packet['baseline']} baseline" if packet.get("baseline") else "")
    L: list[str] = [f"# Auditor packet: {packet['audit']}, {packet['name']}", "",
                    f"Scope: {scope}. Audit date: {adate}. Evidence checked as of {today} (the store's date) and as of the audit date.",
                    "", "Every line below is a claim that cites graph path ids; the claim checker re-ran each path.",
                    "✔ valid, ⚠ partial (proposed or inherited only), ✖ failed or a gap. Nothing failing is hidden.", "",
                    "## Summary", "", f"| Status | As of {today} | On the audit date, {adate} |", "|---|---|---|"]
    for sym, label in ((OK, "Covered directly with valid evidence"), (WARN, "Partial (inherited only or proposed)"),
                       (FAIL, "Not covered (gap or failed proof)")):
        L.append(f"| {sym} {label} | {count('today', sym)} | {count('audit', sym)} |")
    L += [f"| Requirements in scope | {packet['total']} | {packet['total']} |", "",
          f"Claim check, today: {packet['checked']['today']['summary']}. On the audit date: {packet['checked']['audit']['summary']}.", "",
          "| Requirement | Title | Today | Audit day | Direct controls | Reason on the audit date |", "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {_cell(r['id'])} | {_cell(r['title'])} | {r['today_symbol']} | {r['audit_symbol']} | "
                 f"{_cell(', '.join(r['controls']) or 'none')} | {_cell(r['audit_reason'])} |")
    L += ["", "## Requirements", ""]
    for r in rows:
        L += [f"### {r['id']} {r['title']} {r['today_symbol']} / {r['audit_symbol']}", "",
              f"Today ({today}): {r['today_symbol']} {r['today_reason']}.  ",
              f"On {adate}: {r['audit_symbol']} {r['audit_reason']}.", ""]
        if not r["claims"]:
            L += ["No control or proposal exists for this requirement (gap).", ""]
            continue
        by_ctrl: dict[str, list[dict]] = {}
        for c in r["claims"]:
            by_ctrl.setdefault(c["control"], []).append(c)
        for ctrl, cl in by_ctrl.items():
            path = next((p for p in r["today_paths"] if p["control"] == ctrl), None)
            if path:
                owners = ", ".join(people.get(o, o) for o in path["control_owners"]) or "no owner"
                L.append(f"- **Control {ctrl}**: {path['control_title']} (owner {owners}; status {path['control_status']}; "
                         f"mapping approved by {people.get(path['mapping_approved_by'], path['mapping_approved_by'])} on {path['mapping_approved_at']})")
            else:
                L.append(f"- **Control {ctrl}**")
            for c in cl:
                kind = {"direct": "evidence", "inherited": "inherited", "proposal": "proposal"}[c["role"]]
                L.append(f"  - {kind}: {c['text']}")
                L.append(f"    - today {c['today']['symbol']} / audit day {c['audit']['symbol']}  "
                         f"`{', '.join(c['path_ids'])}`")
                for key, label in (("today", "today"), ("audit", "on the audit date")):
                    v = c[key]
                    if v["verdict"] != "verified":
                        L.append(f"    - {v['symbol']} {label}: {_cell(v['reason'])}")
        L.append("")
    L += ["## Open items", ""]
    items = open_items(packet)
    L += items or ["- none: every requirement is covered with valid evidence"]
    L += ["", f"Generated by `crosswalk packet {packet['audit']}`: deterministic, no AI. Not audit advice.", ""]
    return "\n".join(L)


def packet_path(root: str | Path, audit: str, as_of: str) -> Path:
    return Path(root) / "out" / "packets" / f"{audit}-{as_of}.md"


def write_packet(conn: relate.Connection, audit: str, out_dir: str | Path = ".", as_of: str | None = None) -> tuple[Path, dict]:
    """Build and write ``<out_dir>/out/packets/<audit>-<as_of>.md``; returns (path, packet)."""
    packet = build_packet(conn, audit, as_of)
    path = packet_path(out_dir, audit, packet["as_of"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(packet), encoding="utf-8", newline="\n")
    return path, packet


def summary_line(packet: dict) -> str:
    rows = packet["requirements"]
    n = lambda key, s: sum(1 for r in rows if r[f"{key}_symbol"] == s)  # noqa: E731
    return (f"{packet['audit']}: {packet['total']} requirements; today {OK} {n('today', OK)} {WARN} {n('today', WARN)} "
            f"{FAIL} {n('today', FAIL)}; on {packet['audit_date']} {OK} {n('audit', OK)} {WARN} {n('audit', WARN)} "
            f"{FAIL} {n('audit', FAIL)}")
