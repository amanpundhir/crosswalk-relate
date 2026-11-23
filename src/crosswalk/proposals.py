"""Agents propose; they never write facts.  ``create_proposal`` is the only write path agents have.

A proposal is a ``:Proposal {id: 'PR-009', kind, status: 'pending', rationale, created_at, verified,
verify_reason, checks}`` node linked ``-[:BY]->(:Agent)``, ``-[:ABOUT]->`` and ``-[:TARGET]->``:

==================  =====================  ====================================================
kind                ABOUT                  TARGET
==================  =====================  ====================================================
``map``             Control                Requirement (becomes a SATISFIES only on human approve)
``status``          Control                none; the wanted status is the ``new_status`` property
``evidence_request``  Evidence             Person (the request goes to them); ``draft`` is the text
==================  =====================  ====================================================

The verifier (:mod:`crosswalk.verify`) runs inside the same transaction, so a proposal is stored with
its ``verified`` flag, one-line ``verify_reason`` and the full ``checks`` list (a JSON string: Relate
has no map-valued properties).  A proposal that fails verification is still stored (it is the audit
trail, and the review queue shows it as failed); it just cannot be approved without ``force``.

This module also owns the write plumbing shared with :mod:`crosswalk.review`: :func:`open_writer`
(the directory store has ONE writer lease, so a second opener gets ``storage locked``; we wait for
it) and :func:`is_retryable` (a server-hosted store reports a real ``write-write conflict``).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

import relate

from crosswalk.build import resolve_store
from crosswalk.coverage import read_as_of
from crosswalk.verify import normalise_proposal, normalise_status, resolve_target, verify

WRITE_KINDS = ("map", "status", "evidence_request")
ABOUT_LABEL = {"map": "Control", "status": "Control", "evidence_request": "Evidence"}
TARGET_LABEL = {"map": "Requirement", "evidence_request": "Person"}
PROPOSAL_RETRIES = 3


class ProposalError(ValueError):
    """The proposal request itself is malformed (unknown kind, missing fields)."""


# --------------------------------------------------------------------------
# Write plumbing
# --------------------------------------------------------------------------


def is_locked(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "storage locked" in msg or "store locked" in msg


def is_retryable(exc: BaseException) -> bool:
    """True for the engine's retryable errors (``e.retryable``), i.e. a write-write conflict."""
    return bool(getattr(exc, "retryable", False)) or "write-write conflict" in str(exc).lower()


def open_writer(store: str | Path, wait: float = 0.0, poll: float = 0.05,
                on_wait: Callable[[int, BaseException], None] | None = None) -> relate.Connection:
    """Open the directory store for writing with ``autocommit=False``.

    Only one writer holds a directory store at a time (a second opener is refused immediately with
    ``OperationalError: storage locked``).  With ``wait`` > 0 this polls until the lease is free
    (``on_wait(attempt, exc)`` is called on each refusal); otherwise it raises at once.
    """
    path = str(resolve_store(store))
    deadline = time.monotonic() + wait
    attempt = 0
    while True:
        try:
            conn = relate.connect(path)
            conn.autocommit = False
            return conn
        except relate.OperationalError as exc:
            if not is_locked(exc) or time.monotonic() >= deadline:
                raise
            attempt += 1
            if on_wait:
                on_wait(attempt, exc)
            time.sleep(poll)


def _rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def normalise_id(raw: str, prefix: str, width: int = 3) -> str:
    """``'PR-9'``/``'pr-009'`` -> ``'PR-009'`` (ids that are not ``<prefix>-<n>`` are returned as given)."""
    m = re.fullmatch(rf"{prefix}-0*(\d+)", str(raw).strip(), flags=re.I)
    return f"{prefix}-{int(m.group(1)):0{width}d}" if m else str(raw).strip()


def next_id(conn, label: str, prefix: str, width: int = 3) -> str:
    """The next ``<prefix>-<n>`` after the highest existing one (computed inside the caller's transaction)."""
    best = 0
    for r in conn.execute(f"MATCH (n:{label}) RETURN n.id AS id").fetchall():
        m = re.fullmatch(rf"{prefix}-(\d+)", str(r["id"]))
        if m:
            best = max(best, int(m.group(1)))
    return f"{prefix}-{best + 1:0{width}d}"


def as_of_date(conn, at: str | None) -> str:
    return str(at) if at else read_as_of(conn)


# --------------------------------------------------------------------------
# create_proposal
# --------------------------------------------------------------------------


def _create_once(conn, kind, by_agent, about, target, rationale, created_at, extra, before_commit) -> dict:
    conn.autocommit = False
    as_of = read_as_of(conn)
    pid = next_id(conn, "Proposal", "PR")
    if kind == "map":
        target = resolve_target(conn, target)
    elif kind == "status":
        target = normalise_status(target)
    draft = {"id": pid, "kind": kind, "by": by_agent, "about": about, "target": target,
             "rationale": rationale, **extra}
    if kind == "evidence_request" and not target:  # default recipient: the evidence owner
        row = conn.execute("MATCH (p:Person)-[:OWNS]->(:Evidence {id: $e}) RETURN p.id AS id ORDER BY id LIMIT 1",
                           {"e": about}).fetchall()
        target = draft["target"] = row[0]["id"] if row else None
    result = verify(conn, draft, as_of=as_of)

    props: dict[str, Any] = {
        "kind": kind, "status": "pending", "rationale": rationale, "verified": result["verified"],
        "verify_reason": result["reason"], "checks": json.dumps(result["checks"], ensure_ascii=False),
        "crosswalk": result["crosswalk"], "about_id": about, "target_id": target,
    }
    if kind == "status":
        cur = conn.execute("MATCH (c:Control {id: $c}) RETURN c.status AS s", {"c": about}).fetchall()
        props["new_status"] = target
        props["old_status"] = cur[0]["s"] if cur else None
    for key in ("draft", "audit", "target_framework"):
        if extra.get(key) is not None:
            props[key] = extra[key]
    props = {k: v for k, v in props.items() if v is not None}

    conn.execute("MERGE (a:Agent {id: $by}) ON CREATE SET a.name = $by", {"by": by_agent})
    conn.execute("CREATE (p:Proposal {id: $id}) SET p += $props, p.created_at = date($at)",
                 {"id": pid, "props": props, "at": str(created_at) if created_at else as_of})
    conn.execute("MATCH (p:Proposal {id: $id}) MATCH (a:Agent {id: $by}) CREATE (p)-[:BY]->(a)",
                 {"id": pid, "by": by_agent})
    conn.execute(f"MATCH (p:Proposal {{id: $id}}) MATCH (x:{ABOUT_LABEL[kind]} {{id: $x}}) CREATE (p)-[:ABOUT]->(x)",
                 {"id": pid, "x": about})
    if kind in TARGET_LABEL and target:
        conn.execute(f"MATCH (p:Proposal {{id: $id}}) MATCH (x:{TARGET_LABEL[kind]} {{id: $x}}) "
                     f"CREATE (p)-[:TARGET]->(x)", {"id": pid, "x": target})
    if before_commit:
        before_commit(pid)
    bookmark = conn.commit()
    return {"id": pid, "kind": kind, "by": by_agent, "about": about, "target": target, "rationale": rationale,
            "status": "pending", "created_at": str(created_at) if created_at else as_of,
            "verified": result["verified"], "verify_reason": result["reason"],
            "reason_code": result["reason_code"], "checks": result["checks"],
            "crosswalk": result["crosswalk"], "bookmark": bookmark}


def create_proposal(conn: relate.Connection, kind: str, by_agent: str, about: str, target: str | None,
                    rationale: str, *, created_at: str | None = None, retries: int = PROPOSAL_RETRIES,
                    before_commit: Callable[[str], None] | None = None,
                    on_retry: Callable[[int, BaseException], None] | None = None, **extra: Any) -> dict:
    """Write one verified ``:Proposal`` in ONE transaction and return it (with its ``bookmark``).

    ``kind`` is ``map`` (``about`` control, ``target`` requirement), ``status`` (``about`` control,
    ``target`` the wanted status) or ``evidence_request`` (``about`` evidence, ``target`` person,
    ``draft=`` the request text).  ``created_at`` defaults to ``Meta.as_of`` (never the wall clock).
    Other ``extra`` keys (``audit``, ``target_framework``, a claimed ``status``) are passed to the
    verifier; a claimed status other than pending is a failed check, never stored as the status.

    A retryable engine conflict rolls the transaction back and runs it again (the id and every
    check are recomputed), up to ``retries`` times.  ``before_commit(proposal_id)`` and
    ``on_retry(attempt, exc)`` are hooks for the concurrency demo.
    """
    try:
        kind = normalise_proposal({"kind": kind})["kind"]
    except ValueError as exc:
        raise ProposalError(str(exc)) from None
    if kind not in WRITE_KINDS:
        raise ProposalError(f"agents can propose {WRITE_KINDS}, not {kind!r}")
    if not by_agent or not about or not str(rationale or "").strip():
        raise ProposalError("by_agent, about and a rationale are required")
    attempt = 0
    while True:
        attempt += 1
        try:
            out = _create_once(conn, kind, by_agent, about, target, rationale, created_at, extra, before_commit)
            out["attempts"] = attempt
            return out
        except Exception as exc:
            _rollback(conn)
            if is_retryable(exc) and attempt <= retries:
                if on_retry:
                    on_retry(attempt, exc)
                continue
            raise


# --------------------------------------------------------------------------
# Reading proposals
# --------------------------------------------------------------------------

_PROPOSAL_RETURN = (
    "RETURN p.id AS id, p.kind AS kind, p.status AS status, p.rationale AS rationale, "
    "toString(p.created_at) AS created_at, p.verified AS verified, p.verify_reason AS verify_reason, "
    "p.checks AS checks, p.crosswalk AS crosswalk, p.draft AS draft, p.new_status AS new_status, "
    "p.old_status AS old_status, p.audit AS audit, a.id AS by, x.id AS about, t.id AS target, "
    "coalesce(x.id, p.about_id) AS about_id, coalesce(t.id, p.target_id) AS target_id")


def _proposal_query(where: str = "") -> str:
    # the WHERE must follow the first MATCH: after an OPTIONAL MATCH it would only filter that clause
    return ("MATCH (p:Proposal) " + where + "OPTIONAL MATCH (p)-[:BY]->(a:Agent) OPTIONAL MATCH (p)-[:ABOUT]->(x) "
            "OPTIONAL MATCH (p)-[:TARGET]->(t) " + _PROPOSAL_RETURN)


def _row(r) -> dict:
    d = dict(r)
    raw = d.pop("checks", None)
    d["checks"] = json.loads(raw) if raw else []
    d.pop("about", None)
    d.pop("target", None)
    d["about"], d["target"] = d.pop("about_id"), d.pop("target_id")
    return d


def _num(d: dict) -> int:
    m = re.search(r"(\d+)$", d["id"])
    return int(m.group(1)) if m else 0


def get_proposal(conn, proposal_id: str) -> dict | None:
    rows = conn.execute(_proposal_query("WHERE p.id = $id "),
                        {"id": normalise_id(proposal_id, "PR")}).fetchall()
    return _row(rows[0]) if rows else None


def list_proposals(conn, status: str | None = None) -> list[dict]:
    where = "WHERE p.status = $s " if status else ""
    rows = conn.execute(_proposal_query(where), {"s": status} if status else {}).fetchall()
    return sorted((_row(r) for r in rows), key=_num)
