# Mapping quality (Q5), scored against hand-labelled 800-53 targets

40 labelled controls, framework 800-53, top 10 per method. Hit = a primary or acceptable id (`eval/control_labels.yaml`). Recall counts primary ids only. Graph signals are leave-one-out: the control's own approved mappings and proposals are ignored.

| Method | Precision@5 | Recall@10 | MRR | Controls with a hit in top 10 |
|---|---|---|---|---|
| Full-text only | 0.165 | 0.433 | 0.418 | 31/40 |
| Vector only | 0.175 | 0.479 | 0.495 | 32/40 |
| Hybrid (WRRF 0.7/0.3, c=60) | 0.195 | 0.542 | 0.554 | 29/40 |
| Hybrid + graph re-rank (leave-one-out) | 0.195 | 0.562 | 0.573 | 31/40 |

Hybrid: weights 0.7 vector / 0.3 full text, RRF constant 60, 50 candidates per method. Graph re-rank looks at the top 30 hybrid candidates (min-max normalised score; family +0.15, crosswalk +0.25, rejected -1.0). In leave-one-out only the family signal can fire.

The `mapper agent` row of the plan needs a model key and is not part of this table.
