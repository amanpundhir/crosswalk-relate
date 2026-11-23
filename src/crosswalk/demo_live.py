"""``crosswalk demo live-catch``: the "wow" moment of the demo, repeatable and with no API key.

It replays a **recorded** agent answer (``eval/agent-runs/live-catch-recorded.json``: Maya asks "Is MFA
covered for the 800-171 audit?" and the agent confidently claims 03.05.03 is covered by CTRL-REAP-6 and
CTRL-PWP-4) against a FRESH temp copy of the store, so the real store is never touched.  The claim check runs
live: it re-runs both cited paths and prints

* ``✖`` EV-044 expired 2026-12-01 (the only evidence of CTRL-REAP-6), and
* ``⚠`` mapping CTRL-PWP-4 -> 800-171:03.05.03 is proposed (PR-005), not approved,

then drafts the renewal request (a pending proposal in the temp copy) and prints the corrected answer.
Only the latency changes between runs; ``run()`` returns everything else byte-for-byte identical.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import relate

from crosswalk import claims as C
from crosswalk import proposals as P
from crosswalk.build import REPO_ROOT, resolve_store
from crosswalk.coverage import read_as_of

RECORDED = REPO_ROOT / "eval" / "agent-runs" / "live-catch-recorded.json"
DRAFTER = "claim-checker"


def draft_renewal_text(conn: relate.Connection, evidence: str, as_of: str) -> str:
    """A short renewal request for ``evidence``, written from what the graph knows about it."""
    row = conn.execute(
        "MATCH (e:Evidence {id: $e}) OPTIONAL MATCH (e)-[:PROVES]->(c:Control) "
        "RETURN e.title AS title, toString(e.expires_at) AS exp, collect(DISTINCT c.id) AS controls",
        {"e": evidence}).fetchall()[0]
    owner = (C._owner_names(conn, evidence) or ["there"])[0].split()[0]
    controls = ", ".join(sorted(row["controls"])) or "no control"
    when = "expired" if row["exp"] <= as_of else "expires"
    return (f"Hi {owner}, {evidence} ({row['title']}) {when} on {row['exp']} and is the evidence for {controls}. "
            f"Please upload a fresh copy before the next audit.")


def run(store: str | Path = "data/crosswalk", answer: str | Path | dict | None = None, draft: bool = True,
        echo: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Replay the recorded answer on a fresh copy of ``store``.  Returns the checked answer, the corrected answer,
    the drafted request ids and ``latency_ms`` (the claim check only).  ``echo`` prints each output line."""
    say = echo or (lambda s: None)
    rec = C.load_answer(answer or RECORDED) if not isinstance(answer, dict) else answer
    src = resolve_store(store)
    tmp = Path(tempfile.mkdtemp(prefix="crosswalk-live-catch-"))
    dst = tmp / "crosswalk"
    try:
        shutil.copytree(src, dst)
        conn = relate.connect(str(dst), read_only=True)
        try:
            as_of = read_as_of(conn)
            say(f"Crosswalk live catch  (store as of {as_of}, replayed on a fresh temp copy)")
            say("")
            say(f"Maya asks: {rec['question']}")
            say(f"{rec.get('agent', 'agent')} answers: {rec['answer_text']}")
            say("")
            t0 = time.perf_counter()
            checked = C.check_claims(conn, rec, C.PathRegistry())
            latency = (time.perf_counter() - t0) * 1000
            say(f"Claim check (every cited path re-run against the graph in {latency:.0f} ms):")
            for line in C.render_lines(checked):
                say(line)
            say("")
            drafts: list[dict] = []
            renew = [a for a in C.next_actions(conn, checked) if a["action"] == "renew_evidence"]
            texts = {a["evidence"]: draft_renewal_text(conn, a["evidence"], as_of) for a in renew}
        finally:
            conn.close()
        drafted: dict[str, str] = {}
        if draft and renew:
            w = P.open_writer(dst, wait=10)
            try:
                for a in renew:
                    res = P.create_proposal(w, "evidence_request", DRAFTER, a["evidence"], None,
                                            f"request to renew {a['evidence']}", draft=texts[a["evidence"]])
                    drafted[a["evidence"]] = res["id"]
                    drafts.append({"proposal": res["id"], "evidence": a["evidence"], "to": res["target"],
                                   "verified": res["verified"], "draft": texts[a["evidence"]]})
            finally:
                w.close()
        conn = relate.connect(str(dst), read_only=True)
        try:
            corrected = C.corrected_answer(conn, checked, drafted)
        finally:
            conn.close()
        for d in drafts:
            say(f"Drafted {d['proposal']}: evidence request for {d['evidence']} to {d['to']} (pending, nothing sent)")
        if drafts:
            say("")
        say(f"Corrected answer: {corrected['text']}")
        return {"question": rec["question"], "recorded_answer": rec["answer_text"], "checked": checked,
                "corrected": corrected, "drafts": drafts, "latency_ms": latency}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
