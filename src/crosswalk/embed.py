"""Local sentence embeddings for mapping suggestions (no API key, no network at query time).

Model: ``BAAI/bge-small-en-v1.5`` (384-d, MIT licence) run through ``fastembed`` (ONNX, CPU).

Embeddings are computed at build time and cached in ``inputs/embeddings/`` so a rebuild never
needs the model: the cache maps ``id -> (text_sha, vector)`` and an entry is reused only while the
sha of the embedded text is unchanged.  Vectors are stored rounded to 4 decimals (int16 / 1e4,
base64) and the *rounded* values are what the graph stores, so a cache hit and a fresh compute give
a byte-identical store.  If a vector is neither cached nor computable (model missing, offline) the
build logs a warning and leaves the node without an embedding.
"""

from __future__ import annotations

import array
import base64
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_LICENCE = "MIT"
DIM = 384
SCALE = 10_000  # 4 decimals

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = REPO_ROOT / "inputs" / "embeddings" / "bge-small-en-v1.5.json"
MODEL_CACHE_DIR = REPO_ROOT / ".cache" / "fastembed"

log = logging.getLogger("crosswalk.embed")

_ORG_DEFINED = re.compile(r"\[(?:Assignment|Selection)[^\]]*\]|\[organization-defined[^\]]*\]", re.I)
_SPACES = re.compile(r"\s+")


# --------------------------------------------------------------------------
# Text that gets embedded (the cache key hashes exactly this string)
# --------------------------------------------------------------------------


def requirement_text(r: dict) -> str:
    """Title plus statement with the ``[organization-defined ...]`` placeholders removed."""
    body = _SPACES.sub(" ", _ORG_DEFINED.sub("", r.get("text") or "")).strip()
    title = (r.get("title") or "").strip()
    return f"{title}. {body}" if body else title


def control_text(c: dict) -> str:
    """The control statement, with its lead-in context ('During onboarding:') when there is one."""
    text = _SPACES.sub(" ", c.get("text") or "").strip()
    ctx = _SPACES.sub(" ", c.get("context") or "").strip()
    return f"{ctx} {text}".strip() if ctx else text


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def _encode(vec: Sequence[float]) -> str:
    a = array.array("h", (max(-32768, min(32767, round(x * SCALE))) for x in vec))
    if sys.byteorder == "big":
        a.byteswap()
    return base64.b64encode(a.tobytes()).decode("ascii")


def _decode(b64: str) -> list[float]:
    a = array.array("h")
    a.frombytes(base64.b64decode(b64))
    if sys.byteorder == "big":
        a.byteswap()
    return [x / SCALE for x in a]


def load_cache(path: Path | None = None) -> dict[str, dict]:
    """``{id: {"sha": ..., "v": base64}}`` (empty if there is no usable cache)."""
    p = path or CACHE_PATH
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("embedding cache %s is unreadable; ignoring it", p)
        return {}
    if data.get("model") != MODEL_NAME or data.get("dim") != DIM or data.get("scale") != SCALE:
        log.warning("embedding cache %s was made for a different model or format; ignoring it", p)
        return {}
    return dict(data.get("items", {}))


def save_cache(items: dict[str, dict], path: Path | None = None) -> None:
    p = path or CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    head = {"model": MODEL_NAME, "licence": MODEL_LICENCE, "dim": DIM, "scale": SCALE}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f"{json.dumps(k)}: {json.dumps(v)},")
    lines.append('"items": {')
    keys = sorted(items)
    for i, k in enumerate(keys):
        lines.append(f"{json.dumps(k)}: {json.dumps(items[k], sort_keys=True)}" + ("," if i < len(keys) - 1 else ""))
    lines += ["}", "}"]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

_model = None


def model_available() -> bool:
    try:
        _get_model()
        return True
    except Exception:  # noqa: BLE001 - any failure means "no model"
        return False


def _get_model():
    global _model
    if _model is None:
        os.environ.setdefault("DO_NOT_TRACK", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from fastembed import TextEmbedding  # imported lazily: the cache path must not need it

        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(MODEL_CACHE_DIR))
    return _model


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Embed with the local model; vectors are L2-normalised and rounded to 4 decimals."""
    model = _get_model()
    out = []
    for v in model.embed(list(texts)):
        out.append([round(float(x), 4) for x in v])
    return out


# --------------------------------------------------------------------------
# Public: embeddings for a set of (id, text)
# --------------------------------------------------------------------------


def embeddings_for(items: Iterable[tuple[str, str]], write_cache: bool = True,
                   cache_path: Path | None = None) -> dict[str, list[float]]:
    """Vectors for ``(id, text)`` pairs: cache hits first, the model for the rest.

    Returns only the ids it could produce (a missing id means: no cache entry and no model).  When new
    vectors were computed and ``write_cache`` is true the cache file is rewritten with exactly the
    current ids (stale entries dropped), so it stays deterministic and small.
    """
    wanted = sorted(dict(items).items())
    cache = load_cache(cache_path)
    shas = {i: text_sha(t) for i, t in wanted}
    out: dict[str, list[float]] = {}
    todo: list[tuple[str, str]] = []
    for i, t in wanted:
        hit = cache.get(i)
        if hit and hit.get("sha") == shas[i]:
            out[i] = _decode(hit["v"])
        else:
            todo.append((i, t))
    if todo:
        try:
            vecs = embed_texts([t for _, t in todo])
        except Exception as exc:  # noqa: BLE001
            log.warning("embedding model unavailable (%s: %s) and %d of %d texts are not cached; "
                        "those nodes get no embedding", type(exc).__name__, exc, len(todo), len(wanted))
            vecs = []
        for (i, _), v in zip(todo, vecs):
            out[i] = _decode(_encode(v))  # exactly what a cache hit would give
        if vecs and write_cache:
            new = {i: {"sha": shas[i], "v": _encode(out[i])} for i in out}
            if new != {k: cache[k] for k in new if k in cache}:
                save_cache(new, cache_path)
    return out
