"""Export the company pack as the flat spreadsheets a real compliance team would keep (setup A).

    python -I eval/agent_compare/make_spreadsheet.py

Writes ``eval/agent_compare/spreadsheet/``: the untouched ``legacy_tracker.csv`` plus ``evidence_list.csv``,
``controls_list.csv``, ``audits_list.csv``, ``systems_list.csv`` and ``requirements_catalog.csv``.

What is deliberately NOT in there: any graph, any NIST crosswalk (800-53 <-> 800-171 <-> CSF links), the
decision log (earlier approvals and rejections), pending proposals, and any path id.  Everything else a team
would reasonably keep in a tracker is: names, dates, status text, which audits asked for which evidence.
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "eval"))  # python -I ignores PYTHONPATH
import oracle as o  # noqa: E402

OUT = HERE / "spreadsheet"


def _write(name: str, header: list[str], rows: list[list]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main() -> int:
    w = o.world()
    as_of = w["as_of"]
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(o.PACK / "legacy_tracker.csv", OUT / "legacy_tracker.csv")
    people, systems, audits = w["people"], w["systems"], w["audits"]

    requested: dict[str, list[str]] = {}
    for aid in sorted(audits):
        for ev in audits[aid].get("requests", []):
            requested.setdefault(ev, []).append(aid)

    ev_rows = []
    for eid in sorted(w["evidence"]):
        e = w["evidence"][eid]
        expired = o._d(e["expires_at"]) <= as_of
        ev_rows.append([eid, e["title"], e["kind"], people[e["owner"]]["name"], ";".join(sorted(e["proves"])),
                        str(e["collected_at"]), str(e["expires_at"]), "Expired" if expired else "Current",
                        ";".join(requested.get(eid, []))])
    _write("evidence_list.csv",
           ["evidence_id", "title", "type", "owner", "supports_controls", "collected", "expires",
            f"status_as_of_{as_of}", "requested_by_audits"], ev_rows)

    maps: dict[str, list[str]] = {}
    for cid, ms in w["maps"].items():
        maps[cid] = [m["requirement"] for m in ms]
    ctl_rows = []
    for cid in sorted(w["controls"]):
        c = w["controls"][cid]
        lib = w["library"][cid]
        ctl_rows.append([cid, lib["policy_name"], lib["text"], ";".join(people[p]["name"] for p in c["owners"]),
                         ";".join(systems[s]["name"] for s in c["applies_to"]), c["status"],
                         ";".join(maps.get(cid, []))])
    _write("controls_list.csv",
           ["control_id", "policy", "control_statement", "owner", "systems", "implementation_status",
            "requirement_ids"], ctl_rows)

    _write("audits_list.csv", ["audit_id", "name", "framework", "scope", "audit_date"],
           [[a["id"], a["name"], a["framework"], a["scope"].get("baseline", "full framework"), str(a["date"])]
            for a in (audits[k] for k in sorted(audits))])
    _write("systems_list.csv", ["system_id", "name", "criticality", "data_class"],
           [[s["id"], s["name"], s["criticality"], s["data_class"]] for s in (systems[k] for k in sorted(systems))])

    cat = []
    for fw in o.FRAMEWORKS:
        for rid in w["fw_reqs"][fw]:
            r = w["reqs"][rid]
            cat.append([fw, rid, r["family_title"], r["title"]])
    _write("requirements_catalog.csv", ["framework", "requirement_id", "family", "title"], cat)
    print(f"wrote {OUT} ({len(ev_rows)} evidence, {len(ctl_rows)} controls, {len(cat)} catalog rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
