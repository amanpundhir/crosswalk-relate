"""Receipts everywhere: every path id a read command returns resolves in a fresh process; decisions, pending
proposals and owners carry receipts (including the "absence" kind); `stale` and `evidence` are checked against
the YAML/CSV inputs directly (no oracle).

Everything runs on a throw-away store built once per module; nothing here touches data/crosswalk.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

import pytest
import relate
import yaml
from typer.testing import CliRunner

from crosswalk import build as B
from crosswalk import claims as C
from crosswalk import queries as Q
from crosswalk import review as R
from crosswalk.cli import app
from crosswalk.paths import absence_path, make_path, path_id

REPO = Path(__file__).resolve().parents[1]
COMPANY = REPO / "inputs" / "company"
PID = re.compile(r"^P-[0-9a-f]{12}$")
runner = CliRunner()
_REG = C.PathRegistry()  # shared by the tests that only re-run receipts (it fills itself from the graph)


def _yaml(name):
    return yaml.safe_load((COMPANY / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    d = tmp_path_factory.mktemp("receipts") / "crosswalk"
    B.build(d, export=False)
    return d


@pytest.fixture(scope="module")
def conn(store):
    c = relate.connect(str(store), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def as_of():
    return str(_yaml("company.yaml")["as_of"])


def collect(obj) -> tuple[dict[str, dict], set[str]]:
    """``({id: path dict}, {every bare path id string})`` found anywhere inside a JSON-able result."""
    paths: dict[str, dict] = {}
    bare: set[str] = set()
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            n, r = x.get("nodes"), x.get("rels")
            if isinstance(n, list) and isinstance(r, list) and r and len(n) == len(r) + 1:
                paths[path_id(n, r)] = {"nodes": n, "rels": r}
            stack.extend(x.values())
        elif isinstance(x, (list, tuple)):
            stack.extend(x)
        elif isinstance(x, str) and PID.match(x):
            bare.add(x)
    return paths, bare


def _cli(store, *args) -> dict | list:
    res = runner.invoke(app, [*args, "--store", str(store), "--json"])
    assert res.exit_code == 0, (args, res.output)
    return json.loads(res.stdout)


# --------------------------------------------------------------------------
# 1. every path id any read command returns is known to the checker in a fresh process
# --------------------------------------------------------------------------

CLI_CALLS = [
    ("coverage", "-f", "800-53"), ("coverage", "-f", "800-171", "--detail"), ("coverage", "-f", "CSF", "--detail"),
    ("coverage", "--audit", "AUD-171"), ("coverage", "--audit", "AUD-53"),
    ("adopt", "800-171"), ("adopt", "CSF"),
    ("blast",), ("blast", "--days", "90"), ("blast", "--until", "2027-01-15"), ("blast", "--audit", "AUD-171"),
    ("blast", "--audit", "AUD-53"), ("blast", "--audit", "AUD-CSF"), ("blast", "--until", "2027-06-30"),
    ("reuse", "--top", "50"), ("owners",), ("decisions",), ("decisions", "--about", "CTRL-AOTP-11"),
    ("stale",), ("stale", "--all"), ("evidence",), ("evidence", "--audit", "AUD-171", "--status", "expired"),
    ("evidence", "--audit", "AUD-53", "--status", "lapsed"), ("evidence", "--until", "2027-03-01"),
    ("review", "--list"),
]


def _requirements_with_receipts(conn):
    return [r["id"] for r in conn.execute(
        "MATCH (r:Requirement) WHERE (r)<-[:SATISFIES]-() OR (r)<-[:TARGET]-(:Proposal) OR (r)-[:EQUIVALENT_TO]-() "
        "RETURN r.id AS id").fetchall()]


def _check_everything_resolves(conn, as_of, results):
    paths: dict[str, dict] = {}
    bare: set[str] = set()
    for res in results:
        p, b = collect(res)
        paths.update(p)
        bare |= b
    assert paths, "the results hold no paths at all"
    assert bare <= set(paths) | bare  # bare ids are checked below too
    registry = C.PathRegistry()  # a fresh process: nothing remembered
    registry.prepare(conn, set(paths) | bare)
    unknown = sorted(i for i in set(paths) | bare if i not in registry)
    assert not unknown, f"{len(unknown)} path ids no tool can resolve in a fresh process, e.g. {unknown[:5]}"
    for pid, p in paths.items():
        got = C.check_one(conn, pid, registry, as_of)
        assert got["code"] != "unknown_path", pid
        direct = Q.check_path(conn, p["nodes"], p["rels"], as_of)
        assert got["valid"] == direct["valid"] and got["exists"] == direct["exists"], (pid, got, direct)
    return paths


def test_every_cli_json_path_id_resolves_and_reruns_to_its_verdict(store, conn, as_of):
    results = []
    for args in CLI_CALLS:
        results.append(_cli(store, *args))
    reqs = _requirements_with_receipts(conn)
    for req in ("800-171:03.05.03", "800-171:03.03.01", "800-171:03.01.01", "800-53:AC-2", "CSF:GV.OC-01"):
        results.append(_cli(store, "explain", req))  # through the CLI
    results += [Q.explain(conn, req) for req in reqs]  # every requirement with a mapping, proposal or crosswalk link
    paths = _check_everything_resolves(conn, as_of, results)
    # the graph holds paths of every shape the commands emit
    shapes = {tuple(p["rels"]) for p in paths.values()}
    for want in [("SATISFIES<-", "PROVES<-"), ("EQUIVALENT_TO", "SATISFIES<-", "PROVES<-"), ("PROVES",), ("REQUESTS",),
                 ("OWNS",), ("NO_OWNS<-",), ("ON", "ABOUT"), ("ON", "TARGET"), ("TARGET<-", "ABOUT"), ("ABOUT",),
                 ("PROVES", "SATISFIES"), ("PROVES", "SATISFIES", "EQUIVALENT_TO")]:
        assert want in shapes, want


def test_inherited_paths_of_blast_resolve_in_a_fresh_registry(conn, as_of):
    """The run-1 bug: blast's inherited paths (and `still_inherited` rows) were unknown to `crosswalk check`."""
    out = [Q.blast(conn, until=until) for until in ("2027-01-15", "2027-06-30", "2027-12-31")]
    out += [Q.blast(conn, days=30)]
    inherited = [p for b in out for r in b["broken_requirements"] for p in r["inherited_paths"]]
    assert inherited, "the fixture must have inherited paths in blast results"
    registry = C.PathRegistry()
    registry.prepare(conn, [p["id"] for p in inherited])
    assert all(p["id"] in registry for p in inherited)
    answer = {"claims": [{"text": "still met", "path_ids": [inherited[0]["id"]], "kind": "coverage"}]}
    assert C.check_claims(conn, answer, registry)["claims"][0]["verdict"] == "verified"


def test_explain_rows_with_a_valid_flag_check_as_coverage_claims_accordingly(conn, as_of):
    n = 0
    for req in _requirements_with_receipts(conn):
        for row in Q.explain(conn, req)["paths"]:
            ans = {"claims": [{"text": "covered", "kind": "coverage", "path_ids": [row["path_id"]]}]}
            got = C.check_claims(conn, ans, _REG)["claims"][0]
            assert (got["verdict"] == "verified") == row["valid"], (row, got["reasons"])
            assert "unknown_path" not in got["codes"]
            n += 1
    assert n > 50


def test_fabricated_ids_stay_unknown(conn):
    reg = C.PathRegistry()
    reg.prepare(conn, ["P-000000000000"])
    assert "P-000000000000" not in reg
    got = C.check_claims(conn, {"claims": [{"text": "x", "path_ids": ["P-000000000000"]}]}, reg)
    assert got["claims"][0]["codes"] == ["unknown_path"]


def test_suggest_graph_signal_paths_resolve(conn, as_of):
    from crosswalk import suggest as S

    rows = []
    for control in ("CTRL-AOTP-4", "CTRL-AOTP-11", "CTRL-PWP-4"):
        try:
            rows += S.suggest(conn, control, "800-53", k=10, method="hybrid+graph")
        except S.SuggestError:
            pytest.skip("no embeddings in this environment")
    assert any(r["paths"] for r in rows)
    _check_everything_resolves(conn, as_of, [rows])


def test_mcp_tool_ids_resolve(store, conn, as_of, monkeypatch):
    from crosswalk_mcp import server

    monkeypatch.setenv("CROSSWALK_STORE", str(store))
    results = [server.coverage("800-171"), server.coverage(audit="AUD-171"), server.adopt("800-171"),
               server.adopt("CSF"), server.blast(30), server.blast(until="2027-06-30"), server.blast(audit="AUD-171"),
               server.owners(), server.reuse(20), server.decisions(), server.decisions("CTRL-AOTP-11"),
               server.stale(True), server.evidence("AUD-171", "expired"), server.evidence("AUD-53", "lapsed"),
               server.evidence(), server.explain("03.05.03"), server.explain("800-171:03.03.01")]
    _paths, bare = collect(results)
    assert bare
    registry = C.PathRegistry()
    registry.prepare(conn, bare)
    assert not [i for i in bare if i not in registry]


# --------------------------------------------------------------------------
# 2. absence receipts
# --------------------------------------------------------------------------


def _owners_by_control():
    return {c["id"]: c["owners"] for c in _yaml("controls.yaml")}


def test_unowned_control_has_an_absence_receipt_that_verifies(conn, as_of):
    unowned = sorted(c for c, o in _owners_by_control().items() if not o)
    res = Q.owner_risk(conn)
    assert res["unowned_controls"] == unowned and unowned
    for d in res["unowned_detail"]:
        (p,) = d["paths"]
        assert p["rels"] == ["NO_OWNS<-"] and p["nodes"] == [f"Control:{d['control']}", "Person:*"]
        got = Q.check_path(conn, p["nodes"], p["rels"], as_of)
        assert got["exists"] and got["valid"] and not got["problems"]
        ans = {"claims": [{"text": f"{d['control']} is adopted and has no owner", "path_ids": [p["id"]]}]}
        assert C.check_claims(conn, ans, _REG)["claims"][0]["verdict"] == "verified"


def test_absence_receipt_fails_when_the_thing_is_there(conn, as_of):
    owned = next(c for c, o in _owners_by_control().items() if o)
    p = absence_path("Control", owned, "OWNS", "Person", reversed_=True)
    got = Q.check_path(conn, p["nodes"], p["rels"], as_of)
    assert not got["exists"] and not got["valid"]
    assert "not without OWNS" in got["problems"][0] and C.humanise(got["problems"][0]).count(owned) >= 1
    checked = C.check_claims(conn, {"claims": [{"text": "unowned", "path_ids": [p["id"]]}]}, _REG)
    claim = checked["claims"][0]
    assert claim["verdict"] == "failed" and claim["codes"] == ["broken_structure"]
    assert owned in claim["reason"]
    # a control that does not exist, and a control that is not adopted
    ghost = absence_path("Control", "CTRL-NOPE-1", "OWNS", "Person", reversed_=True)
    assert Q.check_path(conn, ghost["nodes"], ghost["rels"], as_of)["problems"] == ["Control:CTRL-NOPE-1 does not exist"]
    lib = conn.execute("MATCH (c:Control) WHERE NOT c.adopted RETURN c.id AS id ORDER BY id LIMIT 1").fetchall()[0]["id"]
    off = absence_path("Control", lib, "OWNS", "Person", reversed_=True)
    got = Q.check_path(conn, off["nodes"], off["rels"], as_of)
    assert got["exists"] and not got["valid"] and got["problems"] == [f"Control:{lib} is not adopted"]


def test_absence_to_a_specific_node_and_after_an_ordinary_prefix(conn, as_of):
    ctrl = "CTRL-AOTP-8"
    mapped = conn.execute("MATCH (:Control {id: $c})-[:SATISFIES]->(r:Requirement) RETURN r.id AS id ORDER BY id",
                          {"c": ctrl}).fetchall()[0]["id"]
    assert not Q.check_path(conn, [f"Control:{ctrl}", f"Requirement:{mapped}"], ["NO_SATISFIES"], as_of)["valid"]
    assert Q.check_path(conn, [f"Control:{ctrl}", "Requirement:800-53:AC-17"], ["NO_SATISFIES"], as_of)["valid"]
    prefix = Q.check_path(conn, ["Person:P-dana-okafor", f"Control:{ctrl}", "Evidence:*"], ["OWNS", "NO_PROVES<-"], as_of)
    assert not prefix["valid"]  # the control has evidence
    with pytest.raises(ValueError):
        Q.check_path(conn, ["Control:X", "Person:*", "Control:Y"], ["NO_OWNS<-", "OWNS"], as_of)


def test_absence_path_ids_are_stable_and_hash_like_any_other(conn):
    p = absence_path("Control", "CTRL-MCP-13", "OWNS", "Person", reversed_=True)
    assert p == make_path(["Control:CTRL-MCP-13", "Person:*"], ["NO_OWNS<-"])
    assert PID.match(p["id"])
    assert C.chain(p["nodes"], p["rels"]) == "CTRL-MCP-13 has no OWNS from any Person"


# --------------------------------------------------------------------------
# 3. decisions and pending proposals
# --------------------------------------------------------------------------


def test_decisions_carry_receipts_that_rerun_valid(conn, as_of):
    rows = R.decisions(conn)
    want = {d["id"]: d for d in _yaml("decisions.yaml")}
    assert {r["id"] for r in rows} == set(want)
    props = {p["id"]: p for p in _yaml("proposals.yaml")}
    for r in rows:
        prop = props[want[r["id"]]["proposal"]]
        assert [p["nodes"] for p in r["paths"]] == [
            [f"Decision:{r['id']}", f"Proposal:{prop['id']}", f"Control:{prop['control']}"],
            [f"Decision:{r['id']}", f"Proposal:{prop['id']}", f"Requirement:{prop['requirement']}"]]
        assert [p["rels"] for p in r["paths"]] == [["ON", "ABOUT"], ["ON", "TARGET"]]
        assert r["path_ids"] == [p["id"] for p in r["paths"]]
        for p in r["paths"]:  # a rejected proposal is on record: the receipt holds, it is not "rejected mapping"
            got = C.check_one(conn, p["id"], _REG, as_of)
            assert got["code"] == "valid", (p, got)


def test_pending_proposals_carry_receipts_that_rerun_as_proposed(conn, as_of):
    queue = R.pending(conn)
    pending = [p for p in _yaml("proposals.yaml") if p["status"] == "pending"]
    assert [p["id"] for p in queue] == sorted(p["id"] for p in pending) and queue
    for row in queue:
        assert row["path_ids"] and len(row["paths"]) == 3
        proposed = next(p for p in row["paths"] if p["rels"] == ["TARGET<-", "ABOUT"])
        got = C.check_one(conn, proposed["id"], _REG, as_of)
        assert got["code"] == "proposed_mapping" and got["status"] == "warn"
        for p in row["paths"]:
            assert C.check_one(conn, p["id"], _REG, as_of)["code"] == "proposed_mapping"


def test_decision_path_is_a_record_not_a_mapping_claim(conn, as_of):
    """A rejected proposal's own path fails as rejected; the Decision receipt on the same proposal holds."""
    row = next(r for r in R.decisions(conn) if r["outcome"] == "rejected")
    rejected = make_path([f"Proposal:{row['proposal']}", f"Control:{row['about']}"], ["ABOUT"])
    assert C.check_one(conn, rejected["id"], _REG, as_of)["code"] == "rejected_mapping"
    assert C.check_one(conn, row["path_ids"][0], _REG, as_of)["code"] == "valid"


# --------------------------------------------------------------------------
# 4. stale: the legacy tracker against the graph (expected values computed from the CSV and YAML directly)
# --------------------------------------------------------------------------


def _tracker():
    with (COMPANY / "legacy_tracker.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _expected_stale(as_of):
    evidence = _yaml("evidence.yaml")
    controls = {c["id"]: c for c in _yaml("controls.yaml")}
    valid: dict[str, list[str]] = {}
    any_ev: dict[str, list[str]] = {}
    for e in evidence:
        for c in e["proves"]:
            any_ev.setdefault(c, []).append(e["id"])
            if str(e["expires_at"]) > as_of:
                valid.setdefault(c, []).append(e["id"])
    out = {}
    for row in _tracker():
        c = row["control_id"]
        if not row["status"].startswith("Compliant"):
            continue
        kinds = set()
        if c not in controls:
            kinds.add("not_adopted")
        else:
            if not any_ev.get(c):
                kinds.add("no_evidence")
            elif not valid.get(c):
                kinds.add("expired_evidence")
            if not controls[c]["owners"]:
                kinds.add("unowned")
        if kinds:
            out[c] = kinds
    return out


def test_tracker_rows_are_loaded_into_the_graph(conn):
    rows = _tracker()
    got = {r["control"]: r for r in conn.execute(
        "MATCH (t:TrackerRow)-[:ABOUT]->(c:Control) RETURN t.id AS id, c.id AS control, t.control AS tc, "
        "t.status_text AS status_text, toString(t.last_reviewed) AS last_reviewed, t.requirements AS requirements").fetchall()}
    assert len(got) == len(rows) == len(_tracker())
    for row in rows:
        g = got[row["control_id"]]
        assert g["tc"] == row["control_id"] and g["last_reviewed"] == row["last_reviewed"]
        assert g["requirements"] == row["requirement_ids"].split(";")
        assert g["status_text"].split()[0] == row["status"].split()[0]  # 'Compliant' / 'In' / 'Gap'
    assert any(g["status_text"] == "Compliant ✔" for g in got.values())


def test_stale_matches_the_csv_and_yaml(conn, as_of):
    res = Q.stale(conn)
    want = _expected_stale(as_of)
    assert {x["control"] for x in res["stale"]} == set(want)
    for x in res["stale"]:
        assert set(x["issue_kinds"]) == want[x["control"]], x["control"]
    no_valid = sorted(c for c, k in want.items() if k & {"no_evidence", "expired_evidence", "not_adopted"})
    assert res["no_valid_evidence"] == no_valid and len(no_valid) >= 4
    assert res["marked_compliant"] == sum(r["status"].startswith("Compliant") for r in _tracker())
    assert res["stale_count"] == len(want)
    assert res["tracker_rows"] == len(_tracker())


def test_stale_receipts_rerun_to_what_they_claim(conn, as_of):
    res = Q.stale(conn, include_ok=True)
    assert any(not x["issues"] for x in res["stale"])  # the consistent rows are listed on request
    for x in res["stale"]:
        assert C.check_one(conn, x["tracker_path"]["id"], _REG, as_of)["valid"]  # the spreadsheet row exists
        for issue in x["issues"]:
            assert issue["paths"], issue
            for p in issue["paths"]:
                got = C.check_one(conn, p["id"], _REG, as_of)
                if issue["kind"] == "expired_evidence":
                    assert got["code"] == "expired_evidence" and "expired" in got["reason"], got
                elif issue["kind"] in ("unowned", "no_evidence", "unmapped"):
                    assert got["code"] == "valid", got  # the absence holds
                elif issue["kind"] == "proposed_only":
                    assert got["code"] == "proposed_mapping", got


def test_stale_cli_and_mcp(store, monkeypatch, as_of):
    out = _cli(store, "stale")
    assert out["as_of"] == as_of and out["no_valid_evidence"]
    res = runner.invoke(app, ["stale", "--store", str(store)])
    assert res.exit_code == 0 and "marked Compliant but without valid evidence" in res.output
    from crosswalk_mcp import server

    monkeypatch.setenv("CROSSWALK_STORE", str(store))
    tool = server.stale()
    assert tool["no_valid_evidence"] == out["no_valid_evidence"]
    assert all(i["path_ids"] for x in tool["stale"] for i in x["issues"])


# --------------------------------------------------------------------------
# 5. evidence (expired-but-requested)
# --------------------------------------------------------------------------


def _requested(audit):
    return {a["id"]: a for a in _yaml("audits.yaml")}[audit]


def test_evidence_expired_for_an_audit_matches_the_yaml(conn, as_of):
    ev = {e["id"]: e for e in _yaml("evidence.yaml")}
    for audit in ("AUD-171", "AUD-53", "AUD-CSF"):
        a = _requested(audit)
        want = sorted(i for i in a["requests"] if str(ev[i]["expires_at"]) <= as_of)
        res = Q.evidence(conn, audit=audit, status="expired")
        assert sorted(res["evidence_ids"]) == want, audit
        assert res["cutoff"] == str(a["date"]) and res["audit"]["id"] == audit
        assert res["counts"]["total"] == len(a["requests"])
        for row in res["evidence"]:
            assert row["status"] == "expired" and row["days_to_expiry"] <= 0
            assert audit in {r["audit"] for r in row["requested_by"]}


def test_evidence_lapsed_by_the_audit_date_matches_the_yaml(conn, as_of):
    ev = {e["id"]: e for e in _yaml("evidence.yaml")}
    a = _requested("AUD-53")
    cut = str(a["date"])
    want = sorted(i for i in a["requests"] if str(ev[i]["expires_at"]) <= cut)
    res = Q.evidence(conn, audit="AUD-53", status="lapsed")
    assert sorted(res["evidence_ids"]) == want and len(want) == 15
    assert sorted(Q.evidence(conn, audit="AUD-53", status="expired,expiring")["evidence_ids"]) == want
    expiring = sorted(i for i in want if str(ev[i]["expires_at"]) > as_of)
    assert sorted(Q.evidence(conn, audit="AUD-53", status="expiring")["evidence_ids"]) == expiring
    valid = sorted(i for i in a["requests"] if str(ev[i]["expires_at"]) > cut)
    assert sorted(Q.evidence(conn, audit="AUD-53", status="valid")["evidence_ids"]) == valid


def test_evidence_until_default_and_filters(conn, as_of):
    ev = _yaml("evidence.yaml")
    d = dt.date.fromisoformat(as_of)
    res = Q.evidence(conn)
    assert res["cutoff"] == (d + dt.timedelta(days=30)).isoformat() and res["counts"]["total"] == len(ev)
    cut = "2027-03-01"
    got = Q.evidence(conn, until=cut)
    by = {e["id"]: e for e in ev}
    for row in got["evidence"]:
        exp = str(by[row["evidence"]]["expires_at"])
        want = "expired" if exp <= as_of else ("expiring" if exp <= cut else "valid")
        assert row["status"] == want
        assert row["collected_at"] == str(by[row["evidence"]]["collected_at"]) and row["expires_at"] == exp
        assert set(row["controls"]) == set(by[row["evidence"]]["proves"])
    assert Q.evidence(conn, until=cut, status="expired")["evidence_ids"] == sorted(
        (e["id"] for e in ev if str(e["expires_at"]) <= as_of), key=lambda i: int(i.split("-")[1]))
    with pytest.raises(ValueError):
        Q.evidence(conn, status="stale")
    with pytest.raises(LookupError):
        Q.evidence(conn, audit="AUD-NOPE")


def test_evidence_receipts_rerun(conn, as_of):
    res = Q.evidence(conn, audit="AUD-171")
    for row in res["evidence"]:
        assert row["proves_paths"] and row["request_paths"]
        for p in row["proves_paths"]:
            got = C.check_one(conn, p["id"], _REG, as_of)
            if row["status"] == "expired":
                assert got["code"] == "expired_evidence" and f"{row['evidence']} expired {row['expires_at']}" in got["reason"]
            else:
                assert got["code"] == "valid"
        for p in row["request_paths"]:
            assert C.check_one(conn, p["id"], _REG, as_of)["valid"] or row["status"] == "expired"


def test_evidence_cli_and_mcp(store, monkeypatch):
    out = _cli(store, "evidence", "--audit", "AUD-171", "--status", "expired")
    c = relate.connect(str(store), read_only=True)
    try:
        assert out["evidence_ids"] == Q.evidence(c, audit="AUD-171", status="expired")["evidence_ids"]
    finally:
        c.close()
    res = runner.invoke(app, ["evidence", "--audit", "AUD-171", "--status", "expired", "--store", str(store)])
    assert res.exit_code == 0 and "EV-044" in res.output
    bad = runner.invoke(app, ["evidence", "--status", "nope", "--store", str(store)])
    assert bad.exit_code == 1
    from crosswalk_mcp import server

    monkeypatch.setenv("CROSSWALK_STORE", str(store))
    tool = server.evidence("AUD-171", "expired")
    assert tool["evidence_ids"] == out["evidence_ids"] and all(e["path_ids"] for e in tool["evidence"])
    with pytest.raises(ValueError):
        server.evidence("AUD-NOPE")
