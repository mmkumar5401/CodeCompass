"""Local vector search over graph entities — turbovec + fastembed.

Optional feature: needs `pip install codecompass-mcp[search]`.
The index lives at `.codecompass/vectors.tvim` (turbovec IdMapIndex) with a
`.codecompass/vectors.meta.json` sidecar holding each entity's payload —
turbovec stores vectors only. Both follow the graph's lifecycle: wiped and
rebuilt wholesale at the end of every ingest, from whatever the graph contains
at that point (parser + agent-inferred nodes).

ponytail: full rebuild each ingest (no per-file incremental updates) — a few
thousand short embeddings take seconds; add incremental indexing only if
ingest time actually hurts.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache

INDEX_FILENAME = "vectors.tvim"
META_FILENAME = "vectors.meta.json"
MODEL = "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX, CPU — no torch, no network calls
DIM = 384
BIT_WIDTH = 4
BATCH_SIZE = 32  # small batches pad less; see _embed_many


class VectorDepsMissing(RuntimeError):
    """Raised when turbovec/fastembed aren't installed."""


def _deps():
    try:
        import numpy
        from fastembed import TextEmbedding
        from turbovec import IdMapIndex
        return numpy, TextEmbedding, IdMapIndex
    except ImportError as exc:
        raise VectorDepsMissing(
            "Vector search needs the optional deps: "
            "pip install 'codecompass-mcp[search]'"
        ) from exc


@lru_cache(maxsize=1)
def _embedder():
    _, TextEmbedding, _ = _deps()
    return TextEmbedding(model_name=MODEL)


def _paths(repo_path: str) -> tuple[str, str]:
    base = os.path.join(repo_path, ".codecompass")
    return (os.path.join(base, INDEX_FILENAME),
            os.path.join(base, META_FILENAME))


def _vector_id(node_id: str) -> int:
    """Stable uint64 id for a graph node id (turbovec ids are uint64)."""
    return int.from_bytes(hashlib.sha1(node_id.encode()).digest()[:8], "big")


def _entity_text(a: dict, description: str) -> str:
    """The string that gets embedded for one entity node."""
    parts = [a.get("kind") or "", a.get("name") or "", a.get("file") or "",
             description]
    return " ".join(p for p in parts if p)


def _embed_many(texts: list[str]):
    """Embed many texts, returned in the caller's original order.

    The model pads every text in a batch out to the longest one in it, so a
    single long description makes its whole batch expensive. Sorting by length
    groups similar sizes together and small batches keep the pad width tight —
    together ~4x faster than one big unsorted batch on a real repo. Vectors
    match unsorted embedding to ~1e-4 (ONNX float noise from the differing pad
    widths, cosine > 0.9999).
    """
    np, _, _ = _deps()
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    sorted_vecs = np.asarray(
        list(_embedder().embed([texts[i] for i in order], batch_size=BATCH_SIZE)),
        dtype=np.float32,
    )
    vecs = np.empty_like(sorted_vecs)
    vecs[np.asarray(order)] = sorted_vecs  # undo the sort
    return vecs


def index_entities(repo_path: str) -> int:
    """Wipe and rebuild the vector index from graph.json. Returns rows indexed."""
    np, _, IdMapIndex = _deps()
    graph_path = os.path.join(repo_path, ".codecompass", "graph.json")
    with open(graph_path) as f:
        nodes = json.load(f).get("nodes", [])

    meta: dict[str, dict] = {}
    texts, ids = [], []
    for a in nodes:
        if a.get("type") != "Entity":
            continue
        node_id = a.get("id") or ""
        description = a.get("description") or ""
        vid = _vector_id(node_id)
        meta[str(vid)] = {
            "name": a.get("name") or "",
            "kind": a.get("kind") or "",
            "file": a.get("file") or "",
            "line": a.get("line") or 0,
            "description": description,
        }
        texts.append(_entity_text(a, description))
        ids.append(vid)
    if not ids:
        return 0

    vecs = _embed_many(texts)
    index = IdMapIndex(dim=DIM, bit_width=BIT_WIDTH)
    index.add_with_ids(vecs, np.asarray(ids, dtype=np.uint64))

    index_path, meta_path = _paths(repo_path)
    index.write(index_path)
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    return len(ids)


@lru_cache(maxsize=4)
def _load_index(index_path: str, meta_path: str, stamp: tuple[float, float]):
    """Load index + meta, cached per process.

    turbovec does its lazy setup on the first search after a load (~100ms on a
    small repo), so re-loading per query made every search pay it. `stamp` is
    the pair of file mtimes: ingest rewrites both files, which changes the key
    and drops the stale entry — no explicit invalidation needed.
    """
    _, _, IdMapIndex = _deps()
    index = IdMapIndex.load(index_path)
    with open(meta_path) as f:
        meta = json.load(f)
    return index, meta


def search_entities(repo_path: str, query: str, limit: int = 10) -> dict:
    """Semantic search over entity names/kinds/files/descriptions."""
    np, _, _ = _deps()
    index_path, meta_path = _paths(repo_path)
    if not os.path.exists(index_path) or not os.path.exists(meta_path):
        return {"query": query, "matches": [], "count": 0,
                "hint": "No vector index yet — run ingest to build it."}

    vec = np.asarray(list(_embedder().embed([query])), dtype=np.float32)
    index, meta = _load_index(
        index_path, meta_path,
        (os.path.getmtime(index_path), os.path.getmtime(meta_path)),
    )
    scores, ids = index.search(vec, k=limit)

    matches = []
    for score, vid in zip(scores[0].tolist(), ids[0].tolist()):
        payload = meta.get(str(vid))
        if payload is None:  # index/meta out of sync — skip rather than guess
            continue
        matches.append({**payload, "score": round(score, 4)})
    return {"query": query, "matches": matches, "count": len(matches)}
