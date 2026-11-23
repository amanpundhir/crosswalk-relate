"""Scripted human reviewer for the repeat-rejection run (docs/plan/05 section C).

    python -I eval/agent_compare/reject_script.py prepare --dest "$TEMP/crosswalk-repeat"
    python -I eval/agent_compare/reject_script.py reject  --store "$TEMP/crosswalk-repeat/store"

``prepare`` copies ``data/crosswalk`` to ``<dest>/store`` (never touch the committed store) and creates
``<dest>/logs``.  ``reject`` is the architect's step between the two sessions: it takes the pending proposals
that session 1 wrote (``by == mapper-s1``), scores each with ``crosswalk suggest`` (method hybrid+graph, the same
ranking the runner saw, computed before any rejection is recorded) and rejects the 3 LOWEST-scoring ones as
reviewer ``P-maya-chen`` with a fixed reason.  Ties go to the lower proposal id; a proposal whose requirement
is not in the control's top 200 suggestions scores 0.0.  Same store in -> same rejections out.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))  # python -I ignores PYTHONPATH

SESSION1_AGENT = "mapper-s1"
REVIEWER = "P-maya-chen"
N_REJECT = 3
REASON = "Rejected by the evaluation script: the control wording does not support this requirement."
POOL = 200


def prepare(dest: Path, source: Path | None = None) -> Path:
    source = source or REPO / "data" / "crosswalk"
    dest = Path(dest)
    store = dest / "store"
    if store.exists():
        shutil.rmtree(store)
    (dest / "logs").mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, store)
    return store


def plan(store: str | Path, agent: str = SESSION1_AGENT, n: int = N_REJECT) -> list[dict]:
    """The proposals to reject, lowest suggest-score first (read-only)."""
    import relate

    from crosswalk import proposals as P
    from crosswalk import suggest as S

    conn = relate.connect(str(store), read_only=True)
    try:
        pend = [p for p in P.list_proposals(conn, "pending")
                if p.get("by") == agent and p.get("kind") == "map" and p.get("target")]
        rows = []
        cache: dict[str, dict[str, float]] = {}
        for p in pend:
            ctl = p["about"]
            if ctl not in cache:
                fw = p["target"].split(":", 1)[0]
                got = S.suggest(conn, ctl, fw, k=POOL, method="hybrid+graph")
                cache[ctl] = {s["id"]: float(s["score"]) for s in got}
            rows.append({"proposal": p["id"], "control": ctl, "requirement": p["target"],
                         "score": cache[ctl].get(p["target"], 0.0)})
    finally:
        conn.close()
    rows.sort(key=lambda r: (r["score"], r["proposal"]))
    return rows[:n]


def reject(store: str | Path, agent: str = SESSION1_AGENT, n: int = N_REJECT, out: Path | None = None) -> list[dict]:
    from crosswalk import proposals as P
    from crosswalk import review as R

    chosen = plan(store, agent, n)
    if len(chosen) < n:
        raise SystemExit(f"only {len(chosen)} pending proposals by {agent}; need at least {n}")
    conn = P.open_writer(store, wait=10)
    try:
        for r in chosen:
            R.decide(conn, r["proposal"], "rejected", REVIEWER, REASON)
    finally:
        conn.close()
    if out is not None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(chosen, indent=2) + "\n", encoding="utf-8")
    return chosen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prepare", help="copy data/crosswalk to <dest>/store")
    p1.add_argument("--dest", required=True)
    p2 = sub.add_parser("reject", help="reject the 3 lowest-score session-1 proposals")
    p2.add_argument("--store", required=True)
    p2.add_argument("--out", help="write the chosen rejections as JSON")
    a = ap.parse_args(argv)
    if a.cmd == "prepare":
        print(prepare(Path(a.dest)))
        return 0
    chosen = reject(a.store, out=Path(a.out) if a.out else None)
    for r in chosen:
        print(f"rejected {r['proposal']}  {r['control']} -> {r['requirement']}  (score {r['score']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
