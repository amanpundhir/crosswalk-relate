"""crosswalk-mcp over a real stdio subprocess: initialize, list tools, call tools, check what was written.

The server runs against a throw-away copy of a freshly built store (``CROSSWALK_STORE``); nothing here touches
data/crosswalk.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import anyio
import pytest
import relate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from crosswalk import build as B

REPO = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {"coverage", "adopt", "blast", "suggest", "explain", "owners", "reuse", "decisions",
                  "propose_mapping", "propose_evidence_request", "propose_status", "check_claims", "stale", "evidence"}


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    dest = tmp_path_factory.mktemp("mcp-store") / "crosswalk"
    B.build(dest, export=False)
    return dest


def _count(store: Path, cypher: str) -> int:
    conn = relate.connect(str(store), read_only=True)
    try:
        return conn.execute(cypher).fetchall()[0]["n"]
    finally:
        conn.close()


def _payload(result) -> dict:
    assert not result.isError, result.content
    if getattr(result, "structuredContent", None):
        sc = result.structuredContent
        return sc["result"] if set(sc) == {"result"} and isinstance(sc["result"], dict) else sc
    return json.loads(result.content[0].text)


async def _session_run(store: Path, scenario):
    env = {**os.environ, "CROSSWALK_STORE": str(store), "DO_NOT_TRACK": "1",
           "PYTHONPATH": os.pathsep.join([str(REPO / "src"), os.environ.get("PYTHONPATH", "")]),
           "PYTHONIOENCODING": "utf-8"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "crosswalk_mcp.server"], env=env, cwd=str(REPO))
    with anyio.fail_after(180):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                return await scenario(session, init)


def test_mcp_server_over_stdio(store, tmp_path):
    work = tmp_path / "crosswalk"
    shutil.copytree(store, work)
    satisfies_before = _count(work, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n")
    proposals_before = _count(work, "MATCH (p:Proposal) RETURN count(p) AS n")
    seen: dict = {}

    async def scenario(session: ClientSession, init):
        seen["server"] = init.serverInfo.name
        tools = {t.name: t for t in (await session.list_tools()).tools}
        seen["tools"] = set(tools)
        assert all(t.description for t in tools.values())

        async def call(name, **args):
            return _payload(await session.call_tool(name, args))

        cov = await call("coverage", framework="800-171")
        assert (cov["framework"], cov["total"]) == ("800-171", 97)
        assert cov["covered"] + cov["inherited"] + cov["gaps"] == cov["total"]
        assert len(cov["gap_list"]) <= 25 and cov["truncated"]["gap_list"]["total"] == cov["gaps"]
        assert all(r["path_ids"] and r["path_ids"][0].startswith("P-") for r in cov["covered_list"])
        assert len(json.dumps(cov)) < 10_000

        ex = await call("explain", requirement="03.05.03")
        assert ex["status"] == "gap"
        expired = ex["paths"][0]
        assert (expired["control"], expired["evidence"], expired["valid"], expired["expires_at"]) == (
            "CTRL-REAP-6", "EV-044", False, "2026-12-01")
        assert ex["proposals"][0]["proposal"] == "PR-005" and ex["proposals"][0]["path_id"].startswith("P-")

        prop = await call("propose_mapping", control="CTRL-REAP-6", requirement="800-171:03.01.01",
                          rationale="MFA on admin VPN supports account management", agent="mapper-agent")
        assert prop["id"] == "PR-009" and prop["status"] == "pending" and prop["path_id"].startswith("P-")
        assert isinstance(prop["verified"], bool) and prop["verify_reason"]
        req = await call("propose_evidence_request", evidence="EV-044", person="P-dana-okafor",
                         draft="Hi Dana, please renew EV-044.", agent="evidence-agent")
        assert req["id"] == "PR-010" and req["verified"] is True
        st = await call("propose_status", control="CTRL-REAP-6", status="at_risk",
                        rationale="its only evidence expired", agent="evidence-agent")
        assert st["id"] == "PR-011" and st["status"] == "pending"

        dec = await call("decisions", about="CTRL-AOTP-11")
        assert dec["total"] == 1 and dec["decisions"][0]["outcome"] == "rejected"
        own = await call("owners")
        assert own["sole_owner_ranking"] and own["unowned_controls"]
        assert own["unowned"][0]["control"] == own["unowned_controls"][0] and own["unowned"][0]["path_ids"]
        assert dec["decisions"][0]["path_ids"] and "paths" not in dec["decisions"][0]
        st_ = await call("stale")
        assert st_["no_valid_evidence"] and all(i["path_ids"] for x in st_["stale"] for i in x["issues"])
        ev_ = await call("evidence", audit="AUD-171", status="expired")
        assert "EV-044" in ev_["evidence_ids"] and all(e["path_ids"] for e in ev_["evidence"])
        assert (await call("reuse", top=3))["top"][0]["evidence"] == "EV-065"
        assert (await call("adopt", framework="800-171"))["inherited_count"] > 0
        assert (await call("blast", days=30))["expiring_evidence"]
        sug = await call("suggest", control="CTRL-AOTP-4", framework="800-53", k=3, method="hybrid+graph")
        assert len(sug["suggestions"]) == 3

        answer = {"question": "Is MFA covered for the 800-171 audit?", "agent": "audit-prep-agent", "claims": [
            {"text": "03.05.03 is covered by CTRL-REAP-6", "kind": "coverage", "path_ids": [expired["path_id"]]},
            {"text": "03.05.03 is covered by CTRL-PWP-4", "kind": "coverage",
             "path_ids": [ex["proposals"][0]["path_id"]]},
            {"text": "my new mapping covers it", "kind": "coverage", "path_ids": [prop["path_id"]]},
            {"text": "made up", "path_ids": ["P-0123456789ab"]},
            {"text": "no receipt"}]}
        chk = await call("check_claims", answer=answer)
        assert [c["symbol"] for c in chk["claims"]] == ["✖", "⚠", "⚠", "✖", "✖"]
        assert chk["claims"][0]["paths"][0]["reason"] == "EV-044 expired 2026-12-01"
        assert chk["claims"][1]["paths"][0]["reason"] == \
            "mapping CTRL-PWP-4 -> 800-171:03.05.03 is proposed (PR-005), not approved"
        assert chk["claims"][3]["codes"] == ["unknown_path"] and chk["claims"][4]["codes"] == ["no_receipt"]
        assert chk["counts"] == {"claims": 5, "verified": 0, "partial": 2, "failed": 3, "paths": 4, "paths_ok": 0}
        assert chk["corrected"]["text"].startswith("Not covered. Renew EV-044 (owner Dana Okafor)")
        assert chk["persisted"]["answer"] == "ANS-001"

        bad = await session.call_tool("explain", {"requirement": "99.99.99"})
        assert bad.isError
        bad = await session.call_tool("propose_mapping", {"control": "CTRL-REAP-6", "requirement": "x", "rationale": " "})
        assert bad.isError  # an empty rationale is refused, not stored

    anyio.run(_session_run, work, scenario)

    assert seen["server"] == "crosswalk" and seen["tools"] == EXPECTED_TOOLS
    # propose tools created proposals only: not one new SATISFIES, no status change, nothing decided
    assert _count(work, "MATCH ()-[s:SATISFIES]->() RETURN count(s) AS n") == satisfies_before
    assert _count(work, "MATCH (p:Proposal) RETURN count(p) AS n") == proposals_before + 3
    assert _count(work, "MATCH (p:Proposal) WHERE p.id IN ['PR-009', 'PR-010', 'PR-011'] AND p.status = 'pending' "
                        "RETURN count(p) AS n") == 3
    assert _count(work, "MATCH (c:Control {id: 'CTRL-REAP-6'}) WHERE c.status = 'implemented' RETURN count(c) AS n") == 1
    assert _count(work, "MATCH (a:Answer)-[:HAS_CLAIM]->(:Claim) RETURN count(a) AS n") == 5


def test_server_reads_beside_a_held_writer(store, tmp_path):
    """A read tool never needs the writer lease: it works while a human's writer has the store open."""
    from crosswalk import proposals as P

    work = tmp_path / "crosswalk"
    shutil.copytree(store, work)
    writer = P.open_writer(work)
    try:
        async def scenario(session, init):
            res = _payload(await session.call_tool("explain", {"requirement": "800-171:03.05.03"}))
            assert res["status"] == "gap"

        anyio.run(_session_run, work, scenario)
    finally:
        writer.close()
