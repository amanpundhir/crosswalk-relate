"""Flow C: two agents write to the same control at the same time.

    python -m crosswalk.demo_concurrency            # both modes, on a throw-away copy of data/crosswalk
    python -m crosswalk.demo_concurrency --mode embedded
    python -m crosswalk.demo_concurrency --mode server

The evidence agent proposes ``CTRL-REAP-6 -> at_risk`` (EV-044, its only evidence, expired) while the
mapper agent proposes ``CTRL-REAP-6 -> 800-53:IA-2(8)``.  The transactions are built to overlap: the
first agent holds its transaction open ("thinking") before it commits.  What Relate does depends on how
the store is opened, and the demo shows both honestly:

``embedded`` (``relate.connect(dir)``, what the CLI and crosswalk-mcp use)
    A directory store has ONE writer lease.  The second ``connect`` is refused at once with
    ``OperationalError: storage locked: ...\\.cypherlite.writer`` (``retryable`` is False).  Nothing
    conflicts because nothing runs concurrently: the lease serialises the writers, and ``open_writer``
    polls until the lease is free.  This is a lock, not a retryable conflict (and not a blocking wait
    inside Relate: the waiting is our poll loop).

``server`` (``relate serve --http``, the process owns the lease, clients open transactions)
    Several transactions can be open at once.  Commits are optimistic, first committer wins: the later
    one fails with ``write-write conflict`` (HTTP 400, code 42000).  Both agents computed the same next
    proposal id, so their commits collide on it; ``create_proposal`` rolls back, recomputes the id and
    commits.  Both land (PR-009 and PR-010), nothing is overwritten.  Two transactions that only
    attach relationships to the same Control node do NOT conflict.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import relate

from crosswalk import proposals as P
from crosswalk.build import DEFAULT_STORE, _relate_cli, resolve_store

CONTROL = "CTRL-REAP-6"
MAPPER_TARGET = "800-53:IA-2(8)"
EVIDENCE_PROPOSAL = ("status", "evidence-agent", CONTROL, "at_risk",
                     "EV-044, the only evidence for this control, expired 2026-12-01.")
MAPPER_PROPOSAL = ("map", "mapper-agent", CONTROL, MAPPER_TARGET,
                   "Replay-resistant authentication is part of what the control's MFA enforces.")


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


class Log:
    def __init__(self, echo: bool = True) -> None:
        self.lines: list[str] = []
        self.echo = echo
        self._lock = threading.Lock()

    def __call__(self, who: str, message: str) -> None:
        line = f"[{dt.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {who:<15} {message}"
        with self._lock:
            self.lines.append(line)
            if self.echo:
                print(line, flush=True)


# --------------------------------------------------------------------------
# A minimal transactional client for `relate serve --http` (stdlib only)
# --------------------------------------------------------------------------


class ServerError(Exception):
    retryable = False


class ServerConflict(ServerError):
    """The engine's ``write-write conflict``: retrying the whole transaction can succeed."""

    retryable = True


class _Rows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return self._rows


class HttpConn:
    """Just enough of the ``relate.Connection`` API (execute / commit / rollback / close) over the
    HTTP Query API v2 transaction endpoints, so :func:`crosswalk.proposals.create_proposal` runs unchanged."""

    def __init__(self, base: str, database: str = "neo4j") -> None:
        self.url = f"{base}/db/{database}/query/v2"
        self.tx: str | None = None
        self.autocommit = False  # accepted for API parity; every HttpConn is transactional

    def _post(self, url: str, body: dict | None = None, method: str = "POST") -> dict:
        req = urllib.request.Request(url, data=json.dumps(body if body is not None else {}).encode(), method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read() or b"{}")
            msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in payload.get("errors", [])) or str(exc)
            self.tx = None  # the server ended the transaction
            cls = ServerConflict if "write-write conflict" in msg else ServerError
            raise cls(msg) from None

    def execute(self, cypher: str, params: dict | None = None) -> _Rows:
        if self.tx is None:
            self.tx = self._post(self.url + "/tx")["transaction"]["id"]
        out = self._post(f"{self.url}/tx/{self.tx}", {"statement": cypher, "parameters": params or {}})
        data = out.get("data", {})
        fields = data.get("fields", [])
        return _Rows([dict(zip(fields, row)) for row in data.get("values", [])])

    def commit(self) -> str:
        tx, self.tx = self.tx, None
        if tx is None:
            return ""
        out = self._post(f"{self.url}/tx/{tx}/commit")
        marks = out.get("bookmarks") or []
        return marks[0] if marks else f"http:{tx}"

    def rollback(self) -> None:
        tx, self.tx = self.tx, None
        if tx is not None:
            try:
                self._post(f"{self.url}/tx/{tx}", method="DELETE")
            except ServerError:
                pass

    def close(self) -> None:
        self.rollback()


class Server:
    """``relate serve --http`` on a free loopback port for the lifetime of the ``with`` block."""

    def __init__(self, store: Path) -> None:
        self.store = store
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Server":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.proc = subprocess.Popen(
            [_relate_cli(), "serve", "--database", str(self.store), "--http", str(self.port), "--auth", "none"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
            env={**__import__("os").environ, "DO_NOT_TRACK": "1"})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("relate serve exited early (is the store open in another process?)")
            try:
                urllib.request.urlopen(self.base + "/", timeout=1).read()
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("relate serve did not come up within 20 s")

    def __exit__(self, *exc) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT)
            proc.wait(timeout=15)  # a clean stop checkpoints the store
        except (subprocess.TimeoutExpired, OSError, ValueError):
            proc.kill()
            proc.wait()


# --------------------------------------------------------------------------
# The two agents
# --------------------------------------------------------------------------


def _agent(spec: tuple, opener: Callable[[], object], start_delay: float, hold: float, log: Log, stats: dict) -> None:
    kind, who, about, target, rationale = spec
    time.sleep(start_delay)
    log(who, f"wants to propose {kind} {about} -> {target}")
    conn = opener()
    log(who, "has the store: transaction open")
    held = [False]

    def before_commit(pid: str) -> None:
        if held[0]:
            log(who, f"rebuilt {pid} (the id and every check were recomputed)")
        else:
            held[0] = True
            log(who, f"built {pid} (verified inside its transaction); thinking for {hold:.1f}s before commit")
            time.sleep(hold)
        log(who, f"committing {pid}")

    def on_retry(attempt: int, exc: BaseException) -> None:
        stats["conflicts"] += 1
        log(who, f"CONFLICT: {type(exc).__name__}: {exc} (retryable={getattr(exc, 'retryable', None)}); "
                 f"rolled back, re-reading and retrying (attempt {attempt + 1})")

    try:
        res = P.create_proposal(conn, kind, who, about, target, rationale, before_commit=before_commit,
                                on_retry=on_retry)
        log(who, f"COMMITTED {res['id']} ({res['bookmark']}) verified={res['verified']} attempts={res['attempts']}")
        stats["committed"].append(res["id"])
    except BaseException as exc:  # reported in the summary; the other agent keeps going
        log(who, f"FAILED: {type(exc).__name__}: {exc}")
        stats["errors"].append(f"{who}: {exc}")
    finally:
        conn.close()
        log(who, "released the store")


def _run_agents(openers: tuple[Callable, Callable], delays: tuple[float, float], holds: tuple[float, float],
                log: Log) -> dict:
    stats = {"conflicts": 0, "waits": 0, "committed": [], "errors": []}
    threads = [threading.Thread(target=_agent, name=spec[1], args=(spec, op, d, h, log, stats))
               for spec, op, d, h in zip((EVIDENCE_PROPOSAL, MAPPER_PROPOSAL), openers, delays, holds)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return stats


def landed(store: Path) -> list[dict]:
    """Proposals about the demo control written by the two agents, read back from the closed store."""
    conn = relate.connect(str(store), read_only=True)
    try:
        return [p for p in P.list_proposals(conn, "pending") if p["about"] == CONTROL and p["by"] in
                ("evidence-agent", "mapper-agent")]
    finally:
        conn.close()


def _summary(mode: str, store: Path, stats: dict, log: Log) -> dict:
    props = landed(store)
    ids = [p["id"] for p in props]
    kinds = sorted(p["kind"] for p in props)
    result = {
        "mode": mode, "conflicts": stats["conflicts"], "lock_waits": stats["waits"], "errors": stats["errors"],
        "committed": sorted(stats["committed"]), "proposals": [{k: p[k] for k in ("id", "kind", "by", "target", "verified")}
                                                               for p in props],
        "both_landed": kinds == ["map", "status"] and len(set(ids)) == 2 and not stats["errors"],
        "lost_updates": 0 if (kinds == ["map", "status"] and len(set(ids)) == 2) else 2 - len(set(ids)),
        "log": log.lines,
    }
    return result


def run_embedded(store: Path, hold: float = 0.8, delay: float = 0.15, echo: bool = True) -> dict:
    """Embedded writers: the writer lease serialises them (``storage locked`` + our poll)."""
    log = Log(echo)
    state = {"waits": 0}

    def opener_for(who: str) -> Callable:
        def on_wait(attempt: int, exc: BaseException) -> None:
            state["waits"] += 1
            if attempt in (1, 5, 10) or attempt % 20 == 0:
                log(who, f"refused: {type(exc).__name__}: {str(exc).split(chr(92))[0]}... "
                         f"(retryable={getattr(exc, 'retryable', None)}); polling the lease (refusal #{attempt})")
        return lambda: P.open_writer(store, wait=60, on_wait=on_wait)

    stats = _run_agents((opener_for("evidence-agent"), opener_for("mapper-agent")), (0.0, delay), (hold, 0.1), log)
    stats["waits"] = state["waits"]
    return _summary("embedded", store, stats, log)


def run_server(store: Path, hold_first: float = 0.6, hold_second: float = 1.2, delay: float = 0.15,
               echo: bool = True) -> dict:
    """Served store: overlapping transactions, first committer wins, the loser retries."""
    log = Log(echo)
    with Server(store) as srv:
        log("server", f"relate serve --http on {srv.base} owns the store's writer lease")
        stats = _run_agents((lambda: HttpConn(srv.base), lambda: HttpConn(srv.base)), (0.0, delay),
                            (hold_first, hold_second), log)
    return _summary("server", store, stats, log)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _copy_store(source: Path) -> Path:
    if not (source / "manifest.json").exists():
        raise SystemExit(f"{source} is not a built store; run `crosswalk build` first")
    dest = Path(tempfile.mkdtemp(prefix="crosswalk-demo-")) / "store"
    shutil.copytree(source, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Two agents propose for the same control at the same time.")
    ap.add_argument("--mode", choices=("embedded", "server", "both"), default="both")
    ap.add_argument("--store", default=str(DEFAULT_STORE), help="Built store to copy (the original is never written).")
    ap.add_argument("--json", action="store_true", help="Print the summaries as JSON instead of the log.")
    args = ap.parse_args(argv)
    source = resolve_store(args.store)
    results = []
    for mode in (["embedded", "server"] if args.mode == "both" else [args.mode]):
        work = _copy_store(source)
        if not args.json:
            print(f"\n=== {mode} writers on a copy of {source.name} ===")
        res = run_embedded(work, echo=not args.json) if mode == "embedded" else run_server(work, echo=not args.json)
        results.append(res)
        if not args.json:
            print(f"--> landed: {', '.join(f'{p['id']} ({p['by']}, {p['kind']})' for p in res['proposals'])}; "
                  f"conflicts retried: {res['conflicts']}; lock refusals: {res['lock_waits']}; "
                  f"lost updates: {res['lost_updates']}")
        shutil.rmtree(work.parent, ignore_errors=True)
    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "log"} for r in results], indent=2))
    return 0 if all(r["both_landed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
