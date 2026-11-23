"""Build the Crosswalk graph store (Relate directory store, JSON snapshot codec).

    crosswalk build            # or: python -m crosswalk.build

The build is deterministic: no wall-clock values are written, every load list is
sorted, and the dated ``:Meta`` node carries ``as_of`` from the company pack plus
hashes of the source files.  ``build()`` closes the connection cleanly (which
forces a checkpoint), asserts the WAL holds no uncheckpointed commits, then
writes ``exports/graph.pretty.json`` by querying the finished store.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import relate
import yaml

from crosswalk import embed as _embed
from crosswalk.sources import comply, nist

log = logging.getLogger("crosswalk.build")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE = REPO_ROOT / "data" / "crosswalk"
DEFAULT_EXPORT = REPO_ROOT / "exports" / "graph.pretty.json"
COMPANY_DIR = REPO_ROOT / "inputs" / "company"
TEMPLATES_DIR = REPO_ROOT / "inputs" / "templates" / "comply"
NIST_RAW_DIR = REPO_ROOT / "inputs" / "nist" / "raw"
QUERIES_DIR = REPO_ROOT / "queries"

CHUNK = 400
WAL_HEADER_BYTES = 8  # an empty, fully checkpointed WAL segment is just a header

# Uniqueness constraints (each also gives an index) and plain range indexes.
UNIQUE_IDS = [
    "Framework", "Family", "Requirement", "Control", "Policy", "Person", "System",
    "Evidence", "Audit", "Agent", "Proposal", "Decision", "TrackerRow", "Meta",
]
# Search indexes (created after the load so they are built once).  The vector index filters by framework.
VECTOR_INDEX = "requirement_embedding"
FULLTEXT_INDEXES = [
    ("requirement_text_ft", "Requirement", ["title", "text"]),
    ("control_text_ft", "Control", ["title", "text"]),
]
RANGE_INDEXES = [
    ("requirement_framework", "Requirement", "framework"),
    ("control_adopted", "Control", "adopted"),
    ("evidence_expires_at", "Evidence", "expires_at"),
]


class BuildError(RuntimeError):
    """The build could not complete, or its post-checks failed."""


class StoreLockedError(BuildError):
    """Another process holds the store open for writing."""


@dataclass
class BuildResult:
    store_dir: Path
    export_path: Path | None
    seconds: float
    size_bytes: int
    nodes: dict[str, int] = field(default_factory=dict)
    relationships: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    embedded: int = 0  # nodes that got an embedding

    @property
    def total_nodes(self) -> int:
        return sum(self.nodes.values())

    @property
    def total_relationships(self) -> int:
        return sum(self.relationships.values())


# --------------------------------------------------------------------------
# Paths and store lifecycle
# --------------------------------------------------------------------------


def resolve_store(store_dir: str | Path) -> Path:
    p = Path(store_dir)
    return p if p.is_absolute() else REPO_ROOT / p


def is_locked_error(exc: BaseException) -> bool:
    return "storage locked" in str(exc).lower() or "store locked" in str(exc).lower()


def _relate_cli() -> str:
    cand = Path(sys.executable).parent / "relate.exe"
    if cand.exists():
        return str(cand)
    cand = Path(sys.executable).parent / "relate"
    if cand.exists():
        return str(cand)
    found = shutil.which("relate")
    if not found:
        raise BuildError("the relate CLI was not found (expected next to the Python interpreter)")
    return found


def _init_json_store(store: Path) -> None:
    """Create an empty directory store and pin its snapshot codec to JSON.

    The Python binding has no snapshot-format option, so the CLI initialises the
    (empty) directory with ``--snapshot-format json`` first.
    """
    store.mkdir(parents=True, exist_ok=False)
    proc = subprocess.run(
        [_relate_cli(), "--database", str(store), "--snapshot-format", "json", "RETURN 1 AS ok"],
        capture_output=True, text=True, env=_env(),
    )
    if proc.returncode != 0:
        raise BuildError(f"could not initialise a JSON-codec store: {proc.stdout}{proc.stderr}")
    codec = read_manifest(store).get("codec")
    if codec != "json":
        raise BuildError(f"store codec is {codec!r}, expected 'json'")


def _env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["DO_NOT_TRACK"] = "1"
    return env


def _remove_store(store: Path) -> None:
    if not store.exists():
        return
    if any(store.iterdir()) and not (store / "manifest.json").exists():
        raise BuildError(f"refusing to delete {store}: not a Relate store (no manifest.json)")
    if (store / "manifest.json").exists():
        # Windows lets us delete files another process holds open, so probe the writer lock first.
        try:
            relate.connect(str(store)).close()
        except relate.OperationalError as exc:
            if is_locked_error(exc):
                raise StoreLockedError(str(exc)) from exc
    try:
        shutil.rmtree(store)
    except PermissionError as exc:
        raise StoreLockedError(
            f"cannot delete {store}: another process has the store open ({exc})"
        ) from exc


def read_manifest(store: Path) -> dict[str, Any]:
    return json.loads((store / "manifest.json").read_text(encoding="utf-8"))


def check_clean_close(store_dir: str | Path) -> None:
    """Assert the store was closed cleanly: JSON codec, checkpointed, empty WAL.

    A cleanly closed store has ``manifest.json`` with ``codec == 'json'`` and
    ``checkpoint_lsn == commit_ts``, a non-empty ``graph.json``, and every
    ``wal/*.log`` segment is only the 8-byte header.  Any larger segment holds
    commits that are not in ``graph.json`` yet.  Raises BuildError otherwise.
    """
    store = resolve_store(store_dir)
    manifest = read_manifest(store)
    problems: list[str] = []
    if manifest.get("codec") != "json":
        problems.append(f"codec is {manifest.get('codec')!r}, expected 'json'")
    if manifest.get("checkpoint_lsn") != manifest.get("commit_ts"):
        problems.append(
            f"checkpoint_lsn {manifest.get('checkpoint_lsn')} != commit_ts {manifest.get('commit_ts')}"
        )
    if not (store / "graph.json").is_file() or (store / "graph.json").stat().st_size == 0:
        problems.append("graph.json is missing or empty")
    for seg in sorted((store / "wal").glob("*.log")):
        if seg.stat().st_size > WAL_HEADER_BYTES:
            problems.append(f"wal/{seg.name} holds uncheckpointed commits ({seg.stat().st_size} bytes)")
    if problems:
        raise BuildError("store was not closed cleanly: " + "; ".join(problems))


def store_size(store: Path) -> int:
    return sum(p.stat().st_size for p in store.rglob("*") if p.is_file())


# --------------------------------------------------------------------------
# Source loading (all pure Python; no Relate)
# --------------------------------------------------------------------------


def _yaml(name: str) -> Any:
    with (COMPANY_DIR / f"{name}.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _sha12(p: Path) -> str:
    data = p.read_bytes()
    if p.suffix in {".yaml", ".csv", ".json", ".md"}:  # same hash with LF or CRLF checkouts
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:12]


def source_shas() -> dict[str, str]:
    """12-hex sha256 of every input the build reads (sorted keys, no timestamps)."""
    shas: dict[str, str] = {}
    for p in sorted(NIST_RAW_DIR.iterdir()):
        if p.is_file() and p.name != ".gitkeep":
            shas[f"nist/{p.name}"] = _sha12(p)
    for p in sorted(COMPANY_DIR.iterdir()):
        if p.suffix in {".yaml", ".csv"}:
            shas[f"company/{p.name}"] = _sha12(p)
    h = hashlib.sha256()
    pol = TEMPLATES_DIR / "policies"
    for p in sorted(pol.glob("*.md")):
        h.update(p.name.encode() + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    shas["templates/comply/policies"] = h.hexdigest()[:12]
    return shas


@dataclass
class Sources:
    frameworks: list[dict]
    families: list[dict]
    requirements: list[dict]
    crosswalk: list[dict]
    controls: list[dict]
    company: dict
    people: list[dict]
    systems: list[dict]
    adopted: list[dict]
    evidence: list[dict]
    audits: list[dict]
    baselines: dict[str, set[str]]
    mappings: list[dict]
    proposals: list[dict]
    decisions: list[dict]
    tracker: list[dict]


def _repair_text(text: str) -> str:
    """Undo UTF-8-read-as-Windows-1252 mojibake in the legacy export (``Compliant ✔`` -> ``Compliant ?``)."""
    try:
        fixed = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return fixed


def load_tracker() -> list[dict]:
    """Rows of the legacy spreadsheet ``legacy_tracker.csv`` (kept in file order, no values invented)."""
    path = COMPANY_DIR / "legacy_tracker.csv"
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            control = (r.get("control_id") or "").strip()
            if not control:
                continue
            rows.append({
                "id": f"TRK-{control}", "control": control,
                "status_text": _repair_text((r.get("status") or "").strip()),
                "owner": (r.get("owner") or "").strip() or None,
                "last_reviewed": (r.get("last_reviewed") or "").strip() or None,
                "requirements": [x.strip() for x in (r.get("requirement_ids") or "").split(";") if x.strip()],
            })
    return rows


def load_sources() -> Sources:
    crosswalk, _warnings = nist.load_crosswalk(NIST_RAW_DIR)
    return Sources(
        frameworks=nist.load_frameworks(),
        families=nist.load_families(NIST_RAW_DIR),
        requirements=nist.load_requirements(NIST_RAW_DIR),
        crosswalk=crosswalk,
        controls=comply.load_controls(TEMPLATES_DIR),
        company=_yaml("company"),
        people=_yaml("people"),
        systems=_yaml("systems"),
        adopted=_yaml("controls"),
        evidence=_yaml("evidence"),
        audits=_yaml("audits"),
        baselines={n: nist.load_baseline(NIST_RAW_DIR, n) for n in nist.FILE_BASELINES},
        mappings=_yaml("mappings"),
        proposals=_yaml("proposals"),
        decisions=_yaml("decisions"),
        tracker=load_tracker(),
    )


# --------------------------------------------------------------------------
# Load steps
# --------------------------------------------------------------------------


def _chunks(rows: list[Any], n: int = CHUNK) -> Iterable[list[Any]]:
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


def _load(conn: relate.Connection, cypher: str, rows: list[dict]) -> None:
    """Run ``UNWIND $rows AS r ...`` in batches; one transaction per call."""
    try:
        for chunk in _chunks(rows):
            conn.execute(cypher, {"rows": chunk})
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _create_schema(conn: relate.Connection) -> None:
    for label in UNIQUE_IDS:
        conn.execute(f"CREATE CONSTRAINT {label.lower()}_id FOR (n:{label}) REQUIRE n.id IS UNIQUE")
    for name, label, prop in RANGE_INDEXES:
        conn.execute(f"CREATE INDEX {name} FOR (n:{label}) ON (n.{prop})")
    conn.commit()


def _create_search_indexes(conn: relate.Connection, with_vectors: bool) -> None:
    for name, label, props in FULLTEXT_INDEXES:
        cols = ", ".join(f"n.{p}" for p in props)
        conn.execute(f"CREATE FULLTEXT INDEX {name} FOR (n:{label}) ON EACH [{cols}]")
    if with_vectors:
        conn.execute(
            f"CREATE VECTOR INDEX {VECTOR_INDEX} FOR (n:Requirement) ON (n.embedding) WITH [n.framework] "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {_embed.DIM}, `vector.similarity_function`: 'cosine'}}}}")
    conn.commit()


def compute_embeddings(s: "Sources") -> tuple[dict[str, list[float]], list[str]]:
    """Vectors for every requirement and control (cache first, then the local model).  Never raises."""
    items = [(r["id"], _embed.requirement_text(r)) for r in s.requirements]
    items += [(c["id"], _embed.control_text(c)) for c in s.controls]
    warnings: list[str] = []
    try:
        emb = _embed.embeddings_for(items)
    except Exception as exc:  # noqa: BLE001 - embeddings are optional
        emb = {}
        warnings.append(f"embeddings unavailable ({type(exc).__name__}: {exc})")
    if len(emb) < len(items):
        warnings.append(f"{len(items) - len(emb)} of {len(items)} nodes have no embedding "
                        f"(no cache entry and the {_embed.MODEL_NAME} model is not available)")
    if not any(i in emb for i, _ in items if i.startswith(("800-", "CSF:"))):
        warnings.append("no requirement embeddings: the vector index was not created, vector search is off")
    for w in warnings:
        log.warning(w)
    return emb, warnings


def _by_id(rows: Iterable[dict], key: str = "id") -> list[dict]:
    return sorted(rows, key=lambda r: nist.natural_key(str(r[key])))


def _populate(conn: relate.Connection, s: Sources, emb: dict[str, list[float]] | None = None) -> None:
    emb = emb or {}
    # --- frameworks, families, requirements ------------------------------
    _load(conn, "UNWIND $rows AS r CREATE (:Framework {id: r.id, name: r.name, version: r.version})",
          _by_id(s.frameworks))
    _load(conn, "UNWIND $rows AS r CREATE (:Family {id: r.id, framework: r.framework, title: r.title})",
          _by_id(s.families))
    _load(conn,
          "UNWIND $rows AS r MATCH (f:Framework {id: r.framework}) MATCH (m:Family {id: r.id}) "
          "CREATE (m)-[:PART_OF]->(f)", _by_id(s.families))
    _load(conn,
          "UNWIND $rows AS r CREATE (:Requirement {id: r.id, framework: r.framework, title: r.title, "
          "text: r.text, is_enhancement: r.is_enhancement, baselines: r.baselines, embedding: r.embedding})",
          [{**r, "is_enhancement": bool(r.get("is_enhancement", False)), "embedding": emb.get(r["id"]),
            "baselines": sorted(n for n, ids in s.baselines.items() if r["id"] in ids)}
           for r in _by_id(s.requirements)])
    _load(conn,
          "UNWIND $rows AS r MATCH (q:Requirement {id: r.id}) MATCH (m:Family {id: r.family_id}) "
          "CREATE (q)-[:PART_OF]->(m)", _by_id(s.requirements))
    _load(conn,
          "UNWIND $rows AS r MATCH (q:Requirement {id: r.id}) MATCH (p:Requirement {id: r.parent_id}) "
          "CREATE (q)-[:ENHANCES]->(p)",
          [r for r in _by_id(s.requirements) if r.get("parent_id")])
    xw = sorted(s.crosswalk, key=lambda e: (e["kind"], nist.natural_key(e["a"]), nist.natural_key(e["b"])))
    _load(conn,
          "UNWIND $rows AS r MATCH (a:Requirement {id: r.a}) MATCH (b:Requirement {id: r.b}) "
          "CREATE (a)-[:EQUIVALENT_TO {source: r.source, kind: r.kind}]->(b)", xw)

    # --- people, systems, policies, controls ------------------------------
    _load(conn, "UNWIND $rows AS r CREATE (:Person {id: r.id, name: r.name, team: r.team, role: r.role})",
          _by_id(s.people))
    _load(conn,
          "UNWIND $rows AS r CREATE (:System {id: r.id, name: r.name, criticality: r.criticality, "
          "data_class: r.data_class})", _by_id(s.systems))

    policies = {}
    for c in s.controls:
        policies.setdefault(c["policy"], {"id": c["policy"], "name": c["policy_name"], "file": c["policy_file"]})
    _load(conn, "UNWIND $rows AS r CREATE (:Policy {id: r.id, name: r.name, file: r.file})",
          _by_id(policies.values()))

    adopted = {a["id"]: a for a in s.adopted}
    ctrl_rows = []
    for c in s.controls:  # library order (policy file order, then n)
        a = adopted.get(c["id"])
        row = {
            "id": c["id"], "policy": c["policy"], "title": c["title"], "text": c["text"],
            "context": c["context"], "text_sha": c["text_sha"], "vague": bool(c["vague"]),
            "adopted": a is not None,
            "status": a["status"] if a else None,
            "owners": sorted(a["owners"]) if a else None,
            "embedding": emb.get(c["id"]),
        }
        ctrl_rows.append(row)
    missing = sorted(set(adopted) - {c["id"] for c in s.controls})
    if missing:
        raise BuildError(f"adopted controls not in the library: {missing}")
    # null-valued properties are simply not stored
    _load(conn,
          "UNWIND $rows AS r CREATE (:Control {id: r.id, policy: r.policy, title: r.title, text: r.text, "
          "context: r.context, text_sha: r.text_sha, vague: r.vague, adopted: r.adopted, "
          "status: r.status, owners: r.owners, embedding: r.embedding})", ctrl_rows)
    _load(conn,
          "UNWIND $rows AS r MATCH (p:Policy {id: r.policy}) MATCH (c:Control {id: r.id}) "
          "CREATE (p)-[:MANDATES]->(c)", ctrl_rows)
    _load(conn,
          "UNWIND $rows AS r MATCH (p:Person {id: r.person}) MATCH (c:Control {id: r.control}) "
          "CREATE (p)-[:OWNS]->(c)",
          [{"person": p, "control": a["id"]} for a in _by_id(s.adopted) for p in sorted(a["owners"])])
    _load(conn,
          "UNWIND $rows AS r MATCH (c:Control {id: r.control}) MATCH (y:System {id: r.system}) "
          "CREATE (c)-[:APPLIES_TO]->(y)",
          [{"control": a["id"], "system": y} for a in _by_id(s.adopted) for y in sorted(a["applies_to"])])

    # --- evidence, audits ---------------------------------------------------
    ev = _by_id(s.evidence)
    _load(conn,
          "UNWIND $rows AS r CREATE (:Evidence {id: r.id, kind: r.kind, title: r.title, location: r.location, "
          "collected_at: date(r.collected_at), expires_at: date(r.expires_at)})", ev)
    _load(conn,
          "UNWIND $rows AS r MATCH (e:Evidence {id: r.evidence}) MATCH (c:Control {id: r.control}) "
          "CREATE (e)-[:PROVES]->(c)",
          [{"evidence": e["id"], "control": c} for e in ev for c in sorted(e["proves"])])
    _load(conn,
          "UNWIND $rows AS r MATCH (p:Person {id: r.person}) MATCH (e:Evidence {id: r.evidence}) "
          "CREATE (p)-[:OWNS]->(e)",
          [{"person": e["owner"], "evidence": e["id"]} for e in ev if e.get("owner")])
    audits = _by_id(s.audits)
    _load(conn, "UNWIND $rows AS r CREATE (:Audit {id: r.id, name: r.name, date: date(r.date), "
          "scope_baseline: r.scope_baseline})",
          [{**a, "scope_baseline": (a.get("scope") or {}).get("baseline")} for a in audits])
    _load(conn,
          "UNWIND $rows AS r MATCH (a:Audit {id: r.id}) MATCH (f:Framework {id: r.framework}) "
          "CREATE (a)-[:SCOPES]->(f)", audits)
    _load(conn,
          "UNWIND $rows AS r MATCH (a:Audit {id: r.audit}) MATCH (e:Evidence {id: r.evidence}) "
          "CREATE (a)-[:REQUESTS]->(e)",
          [{"audit": a["id"], "evidence": e} for a in audits for e in sorted(a["requests"])])

    # --- approved mappings ----------------------------------------------------
    maps = sorted(s.mappings, key=lambda m: (m["control"], nist.natural_key(m["requirement"])))
    _load(conn,
          "UNWIND $rows AS r MATCH (c:Control {id: r.control}) MATCH (q:Requirement {id: r.requirement}) "
          "CREATE (c)-[:SATISFIES {approved_by: r.approved_by, approved_at: date(r.approved_at)}]->(q)", maps)

    # --- agent memory: proposals and decisions --------------------------------
    props = _by_id(s.proposals)
    agents = sorted({p["by"] for p in props})
    _load(conn, "UNWIND $rows AS r CREATE (:Agent {id: r.name, name: r.name})", [{"name": a} for a in agents])
    _load(conn,
          "UNWIND $rows AS r CREATE (:Proposal {id: r.id, kind: 'map', status: r.status, "
          "rationale: r.rationale, created_at: date(r.created_at)})", props)
    _load(conn,
          "UNWIND $rows AS r MATCH (p:Proposal {id: r.id}) MATCH (c:Control {id: r.control}) "
          "MATCH (q:Requirement {id: r.requirement}) MATCH (a:Agent {id: r.by}) "
          "CREATE (p)-[:ABOUT]->(c) CREATE (p)-[:TARGET]->(q) CREATE (p)-[:BY]->(a)", props)
    decs = _by_id(s.decisions)
    _load(conn,
          "UNWIND $rows AS r CREATE (:Decision {id: r.id, outcome: r.decision, reason: r.reason, "
          "by: r.decided_by, at: date(r.decided_at)})", decs)
    _load(conn,
          "UNWIND $rows AS r MATCH (d:Decision {id: r.id}) MATCH (p:Proposal {id: r.proposal}) "
          "CREATE (d)-[:ON]->(p)", decs)

    # --- the legacy tracker: what the spreadsheet says, next to the graph -----------
    tracker = sorted(s.tracker, key=lambda t: nist.natural_key(t["control"]))
    lib = {c["id"] for c in s.controls}
    unknown = sorted({t["control"] for t in tracker} - lib)
    if unknown:
        raise BuildError(f"legacy_tracker.csv rows about controls not in the library: {unknown}")
    if len({t["id"] for t in tracker}) != len(tracker):
        raise BuildError("legacy_tracker.csv lists a control twice")
    _load(conn,
          "UNWIND $rows AS r CREATE (:TrackerRow {id: r.id, control: r.control, status_text: r.status_text, "
          "owner: r.owner, last_reviewed: CASE WHEN r.last_reviewed IS NULL THEN null ELSE date(r.last_reviewed) END, "
          "requirements: r.requirements})", tracker)
    _load(conn,
          "UNWIND $rows AS r MATCH (t:TrackerRow {id: r.id}) MATCH (c:Control {id: r.control}) "
          "CREATE (t)-[:ABOUT]->(c)", tracker)

    # --- meta ---------------------------------------------------------------------
    _load(conn,
          "UNWIND $rows AS r CREATE (:Meta {id: 'meta', company: r.company, as_of: date(r.as_of), "
          "built_at_source_shas: r.shas})",
          [{"company": s.company["name"], "as_of": str(s.company["as_of"]),
            "shas": json.dumps(source_shas(), sort_keys=True)}])


def _expected_counts(s: Sources) -> tuple[dict[str, int], dict[str, int]]:
    reqs = s.requirements
    policies = {c["policy"] for c in s.controls}
    agents = {p["by"] for p in s.proposals}
    nodes = {
        "Framework": len(s.frameworks), "Family": len(s.families), "Requirement": len(reqs),
        "Control": len(s.controls), "Policy": len(policies), "Person": len(s.people),
        "System": len(s.systems), "Evidence": len(s.evidence), "Audit": len(s.audits),
        "Agent": len(agents), "Proposal": len(s.proposals), "Decision": len(s.decisions),
        "TrackerRow": len(s.tracker), "Meta": 1,
    }
    rels = {
        "PART_OF": len(s.families) + len(reqs),
        "ENHANCES": sum(1 for r in reqs if r.get("parent_id")),
        "EQUIVALENT_TO": len(s.crosswalk),
        "MANDATES": len(s.controls),
        "OWNS": sum(len(a["owners"]) for a in s.adopted) + sum(1 for e in s.evidence if e.get("owner")),
        "APPLIES_TO": sum(len(a["applies_to"]) for a in s.adopted),
        "PROVES": sum(len(e["proves"]) for e in s.evidence),
        "SCOPES": len(s.audits),
        "REQUESTS": sum(len(a["requests"]) for a in s.audits),
        "SATISFIES": len(s.mappings),
        "ABOUT": len(s.proposals) + len(s.tracker), "TARGET": len(s.proposals), "BY": len(s.proposals),
        "ON": len(s.decisions),
    }
    return nodes, rels


def count_graph(conn: relate.Connection) -> tuple[dict[str, int], dict[str, int]]:
    nodes = {
        r["l"]: r["c"]
        for r in conn.execute("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c").fetchall()
    }
    rels = {r["t"]: r["c"] for r in conn.execute("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c").fetchall()}
    return dict(sorted(nodes.items())), dict(sorted(rels.items()))


# --------------------------------------------------------------------------
# Pretty export
# --------------------------------------------------------------------------


def _jsonable(v: Any) -> Any:
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))


def export_pretty(store_dir: str | Path, out_path: str | Path) -> tuple[int, int]:
    """Write all nodes and relationships, sorted, one per line, from a store (read-only)."""
    conn = relate.connect(str(resolve_store(store_dir)), read_only=True)
    try:
        nodes = []
        for r in conn.execute("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props").fetchall():
            props = _jsonable(r["props"])
            props.pop("embedding", None)  # 384 floats per node: kept in inputs/embeddings, not in the diffable export
            nodes.append({"id": props.get("id"), "labels": sorted(r["labels"]), "properties": props})
        nodes.sort(key=lambda n: (",".join(n["labels"]), str(n["id"])))
        rels = []
        for r in conn.execute(
            "MATCH (a)-[r]->(b) RETURN type(r) AS type, labels(a) AS al, a.id AS aid, labels(b) AS bl, "
            "b.id AS bid, properties(r) AS props"
        ).fetchall():
            rels.append({
                "type": r["type"],
                "from": {"labels": sorted(r["al"]), "id": r["aid"]},
                "to": {"labels": sorted(r["bl"]), "id": r["bid"]},
                "properties": _jsonable(r["props"]),
            })
        rels.sort(key=lambda r: (
            r["type"], ",".join(r["from"]["labels"]), str(r["from"]["id"]),
            ",".join(r["to"]["labels"]), str(r["to"]["id"]), _dump(r["properties"]),
        ))
    finally:
        conn.close()
    lines = ['{"nodes": [']
    lines += [_dump(n) + ("," if i < len(nodes) - 1 else "") for i, n in enumerate(nodes)]
    lines += ['], "relationships": [']
    lines += [_dump(r) + ("," if i < len(rels) - 1 else "") for i, r in enumerate(rels)]
    lines += ["]}"]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(nodes), len(rels)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def build(store_dir: str | Path = "data/crosswalk", fresh: bool = True,
          export_path: str | Path | None = None, export: bool = True) -> BuildResult:
    """Build the store. ``fresh`` deletes and recreates it (the only supported mode)."""
    t0 = time.perf_counter()
    store = resolve_store(store_dir)
    if not fresh:
        raise BuildError("fresh=False is not supported: the build is always a full, deterministic rebuild")
    _remove_store(store)
    s = load_sources()
    emb, warnings = compute_embeddings(s)
    has_vectors = any(r["id"] in emb for r in s.requirements)
    _init_json_store(store)

    try:
        conn = relate.connect(str(store))
    except relate.OperationalError as exc:
        if is_locked_error(exc):
            raise StoreLockedError(str(exc)) from exc
        raise
    try:
        conn.autocommit = False
        _create_schema(conn)
        _populate(conn, s, emb)
        _create_search_indexes(conn, has_vectors)
        nodes, rels = count_graph(conn)
    finally:
        conn.close()  # checkpoint: graph.json is rewritten, the WAL is emptied

    check_clean_close(store)
    exp_nodes, exp_rels = _expected_counts(s)
    if nodes != exp_nodes or rels != exp_rels:
        diff = {k: (nodes.get(k), exp_nodes.get(k)) for k in set(nodes) | set(exp_nodes) if nodes.get(k) != exp_nodes.get(k)}
        diff |= {k: (rels.get(k), exp_rels.get(k)) for k in set(rels) | set(exp_rels) if rels.get(k) != exp_rels.get(k)}
        raise BuildError(f"loaded counts differ from sources (loaded, expected): {diff}")

    out: Path | None = None
    if export:
        if export_path is not None:
            out = Path(export_path)
        elif store == DEFAULT_STORE:
            out = DEFAULT_EXPORT
        else:
            out = store.with_name(store.name + ".pretty.json")
        export_pretty(store, out)
    return BuildResult(store, out, time.perf_counter() - t0, store_size(store), nodes, rels,
                       warnings, sum(1 for r in [*s.requirements, *s.controls] if r["id"] in emb))


if __name__ == "__main__":
    res = build()
    print(f"built {res.store_dir}: {res.total_nodes} nodes, {res.total_relationships} relationships "
          f"in {res.seconds:.1f}s")
