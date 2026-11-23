"""Path ids: stable, replayable receipts for facts about the graph.

A *path* is an alternating list of nodes and relationships that proves one fact, for example
"requirement 800-171:03.01.01 is covered": ``Requirement <- Control <- Evidence``.  Every query
result row that asserts coverage, inheritance or evidence carries the path ids that prove it plus
the node and relationship lists, so a claim checker can re-run exactly that path later
(``queries/check_path.cypher``) and say whether it still exists and is still valid.

Canonical format
----------------
::

    <node> "|" <rel> "|" <node> ["|" <rel> "|" <node> ...]

* A node is ``Label:id`` (the id is the node's ``id`` property and may itself contain colons),
  e.g. ``Requirement:800-171:03.01.01``, ``Control:CTRL-AOTP-8``, ``Evidence:EV-012``.
* A relationship token is the relationship TYPE as it is *traversed from the left node to the right
  node*: ``SATISFIES`` if it is walked along its stored direction (left node is the start node), and
  ``SATISFIES<-`` if it is walked against it.  In the graph a control satisfies a requirement
  (``(:Control)-[:SATISFIES]->(:Requirement)``) and evidence proves a control
  (``(:Evidence)-[:PROVES]->(:Control)``), so the usual coverage path read from the requirement is::

      Requirement:800-171:03.01.01|SATISFIES<-|Control:CTRL-AOTP-8|PROVES<-|Evidence:EV-012

* ``EQUIVALENT_TO`` is a symmetric crosswalk link whose stored direction carries no meaning, so its
  token is always the bare ``EQUIVALENT_TO`` (any ``<-`` is stripped) and a checker ignores direction.
* Paths are oriented as written (a path and its reverse have different ids); producers always
  start from the thing being explained (requirement, evidence, person ...).
* An *absence* receipt proves that something is NOT there.  Its last hop has the token ``NO_<TYPE>`` (or
  ``NO_<TYPE><-``) and its last node is ``Label:*`` (any node of that label) or one specific node:
  ``Control:CTRL-X|NO_OWNS<-|Person:*`` = "control CTRL-X exists, is adopted and nobody owns it".

``path_id`` is ``"P-"`` plus the first 12 hex characters of the SHA-256 of that canonical string
(UTF-8).  It is pure and deterministic: no clock, no store state.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

SYMMETRIC_RELS = frozenset({"EQUIVALENT_TO"})
REVERSED_MARK = "<-"


def normalise_rel(rel: str) -> str:
    """Canonical relationship token: symmetric types lose any direction mark."""
    base = rel[: -len(REVERSED_MARK)] if rel.endswith(REVERSED_MARK) else rel
    return base if base in SYMMETRIC_RELS else rel


def split_rel(rel: str) -> tuple[str, bool]:
    """``'SATISFIES<-'`` -> ``('SATISFIES', True)``; ``'PROVES'`` -> ``('PROVES', False)``."""
    if rel.endswith(REVERSED_MARK):
        return rel[: -len(REVERSED_MARK)], True
    return rel, False


def split_node(node: str) -> tuple[str, str]:
    """``'Requirement:800-171:03.01.01'`` -> ``('Requirement', '800-171:03.01.01')``."""
    label, sep, ident = node.partition(":")
    if not sep or not label or not ident:
        raise ValueError(f"node reference must look like 'Label:id', got {node!r}")
    return label, ident


def node_ref(label: str, ident: str) -> str:
    return f"{label}:{ident}"


def canonical(nodes: Iterable[str], rels: Iterable[str]) -> str:
    """The canonical string that ``path_id`` hashes."""
    nodes, rels = list(nodes), [normalise_rel(r) for r in rels]
    if len(nodes) != len(rels) + 1 or not rels:
        raise ValueError(f"a path needs n nodes and n-1 >= 1 relationships, got {len(nodes)} and {len(rels)}")
    for n in nodes:
        split_node(n)
    parts = [nodes[0]]
    for rel, node in zip(rels, nodes[1:]):
        parts += [rel, node]
    return "|".join(parts)


def id_of_canonical(text: str) -> str:
    """``P-`` + first 12 hex of sha256 of an already canonical string."""
    return "P-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def path_id(nodes: list[str], rels: list[str]) -> str:
    """Stable id of a path: ``P-`` + first 12 hex of sha256 of its canonical string."""
    return id_of_canonical(canonical(nodes, rels))


def make_path(nodes: list[str], rels: list[str]) -> dict:
    """``{"id", "nodes", "rels"}`` for a path (relationship tokens normalised)."""
    rels = [normalise_rel(r) for r in rels]
    return {"id": path_id(nodes, rels), "nodes": list(nodes), "rels": rels}


ABSENT_PREFIX = "NO_"
ANY = "*"


def is_absence(rel: str) -> bool:
    """True for an *absence* hop (``NO_OWNS<-``): the relationship must NOT exist."""
    return split_rel(rel)[0].startswith(ABSENT_PREFIX)


def absence_path(label: str, ident: str, rel_type: str, other_label: str, other_id: str = ANY,
                 reversed_: bool = False) -> dict:
    """Receipt for something that is NOT in the graph: ``label:ident`` has no ``rel_type`` relationship to
    ``other_label:other_id`` (``*`` = to any node of that label).

    ``absence_path("Control", "CTRL-X", "OWNS", "Person", reversed_=True)`` is
    ``Control:CTRL-X|NO_OWNS<-|Person:*``: the control exists (and, for a control, is adopted) and nobody
    owns it.  An absence hop may only be the LAST hop of a path; ``queries.check_path`` verifies it.
    """
    return make_path([node_ref(label, ident), node_ref(other_label, other_id)],
                     [ABSENT_PREFIX + rel_type + (REVERSED_MARK if reversed_ else "")])


def make_paths(rows: Iterable[dict]) -> list[dict]:
    """Paths from rows holding ``nodes`` and ``rels`` lists, de-duplicated by id, sorted by id."""
    seen: dict[str, dict] = {}
    for row in rows:
        p = make_path(row["nodes"], row["rels"])
        seen.setdefault(p["id"], p)
    return [seen[k] for k in sorted(seen)]
