"""Mapping-quality evaluation (KPI section B): how well does Q5 rank the right 800-53 requirements?

    python eval/mapping_eval.py [--store data/crosswalk] [--out-dir eval]

Ground truth is ``eval/control_labels.yaml``: for 40 hand-labelled controls, ``primary`` 800-53 ids (the best
targets) and ``acceptable`` ids (also defensible).  For each method (full text, vector, hybrid, hybrid+graph)
the top 10 suggestions are scored with

* Precision@5  hit = a primary or acceptable id in the top 5, divided by 5
* Recall@10    primary ids found in the top 10, divided by the number of primary ids
* MRR          1 / rank of the first primary-or-acceptable id in the top 10 (0 if none)

All numbers are macro-averaged over the controls.  Graph signals are leave-one-out: the control's own approved
SATISFIES edges and its own proposals/decisions are ignored (``ignore_own=True``), so nothing is read off the
answer.  The output is deterministic (no timestamps); it writes ``mapping_scores.json`` and ``mapping_scores.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import relate  # noqa: E402
import yaml  # noqa: E402

from crosswalk import suggest as S  # noqa: E402

LABELS = REPO_ROOT / "eval" / "control_labels.yaml"
FRAMEWORK = "800-53"
K = 10
METHOD_NAMES = {
    "fulltext": "Full-text only",
    "vector": "Vector only",
    "hybrid": "Hybrid (WRRF 0.7/0.3, c=60)",
    "hybrid+graph": "Hybrid + graph re-rank (leave-one-out)",
}


def load_labels(path: Path = LABELS) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [row for row in yaml.safe_load(fh) if isinstance(row, dict) and "control" in row]


def score_one(ranked: list[str], primary: set[str], acceptable: set[str]) -> dict:
    good = primary | acceptable
    top5, top10 = ranked[:5], ranked[:K]
    first = next((i for i, rid in enumerate(top10, 1) if rid in good), None)
    return {
        "precision_at_5": sum(1 for r in top5 if r in good) / 5,
        "recall_at_10": len(primary & set(top10)) / len(primary) if primary else 0.0,
        "reciprocal_rank": 1 / first if first else 0.0,
        "first_hit_rank": first,
    }


def run_eval(conn: relate.Connection, labels: list[dict] | None = None, methods=S.METHODS) -> dict:
    labels = labels if labels is not None else load_labels()
    shas = {r["id"]: r["sha"] for r in conn.execute(
        "MATCH (c:Control) RETURN c.id AS id, c.text_sha AS sha").fetchall()}
    stale = sorted(row["control"] for row in labels if shas.get(row["control"]) != row.get("text_sha"))
    per: dict[str, dict] = {m: {} for m in methods}
    for row in labels:
        cid = row["control"]
        primary, acceptable = set(row["primary"]), set(row.get("acceptable") or [])
        for m in methods:
            res = S.suggest(conn, cid, FRAMEWORK, K, m, ignore_own=True)
            per[m][cid] = score_one([r["id"] for r in res], primary, acceptable)
    n = len(labels)
    summary = {}
    for m in methods:
        rows = per[m].values()
        summary[m] = {
            "precision_at_5": round(sum(r["precision_at_5"] for r in rows) / n, 4),
            "recall_at_10": round(sum(r["recall_at_10"] for r in rows) / n, 4),
            "mrr": round(sum(r["reciprocal_rank"] for r in rows) / n, 4),
            "controls_with_a_hit_in_top_10": sum(1 for r in rows if r["first_hit_rank"]),
        }
    return {
        "framework": FRAMEWORK,
        "controls": n,
        "k": K,
        "leave_one_out": True,
        "stale_labels": stale,
        "config": {"w_vec": S.W_VEC, "w_ft": S.W_FT, "rrf_c": S.RRF_C, "pool": S.POOL,
                   "graph_pool": S.GRAPH_POOL, "boost_family": S.BOOST_FAMILY,
                   "boost_crosswalk": S.BOOST_CROSSWALK, "penalty_rejected": S.PENALTY_REJECTED},
        "methods": summary,
        "per_control": {m: {c: per[m][c] for c in sorted(per[m])} for m in methods},
    }


def to_markdown(result: dict) -> str:
    lines = [
        "# Mapping quality (Q5), scored against hand-labelled 800-53 targets",
        "",
        f"{result['controls']} labelled controls, framework {result['framework']}, top {result['k']} per method. "
        "Hit = a primary or acceptable id (`eval/control_labels.yaml`). Recall counts primary ids only. "
        "Graph signals are leave-one-out: the control's own approved mappings and proposals are ignored.",
        "",
        "| Method | Precision@5 | Recall@10 | MRR | Controls with a hit in top 10 |",
        "|---|---|---|---|---|",
    ]
    for m, v in result["methods"].items():
        lines.append(f"| {METHOD_NAMES.get(m, m)} | {v['precision_at_5']:.3f} | {v['recall_at_10']:.3f} | "
                     f"{v['mrr']:.3f} | {v['controls_with_a_hit_in_top_10']}/{result['controls']} |")
    cfg = result["config"]
    lines += [
        "",
        f"Hybrid: weights {cfg['w_vec']} vector / {cfg['w_ft']} full text, RRF constant {cfg['rrf_c']}, "
        f"{cfg['pool']} candidates per method. Graph re-rank looks at the top {cfg['graph_pool']} hybrid candidates "
        f"(min-max normalised score; family +{cfg['boost_family']}, crosswalk +{cfg['boost_crosswalk']}, "
        f"rejected -{cfg['penalty_rejected']}). In leave-one-out only the family signal can fire.",
        "",
        "The `mapper agent` row of the plan needs a model key and is not part of this table.",
    ]
    if result["stale_labels"]:
        lines += ["", f"Labels whose control text changed since labelling: {', '.join(result['stale_labels'])}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", default="data/crosswalk")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "eval"))
    args = ap.parse_args(argv)
    store = Path(args.store)
    store = store if store.is_absolute() else REPO_ROOT / store
    conn = relate.connect(str(store), read_only=True)
    try:
        result = run_eval(conn)
    finally:
        conn.close()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "mapping_scores.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (out / "mapping_scores.md").write_text(to_markdown(result), encoding="utf-8", newline="\n")
    print(to_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
