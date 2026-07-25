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

    vecs = np.asarray(list(_embedder().embed(texts)), dtype=np.float32)
    index = IdMapIndex(dim=DIM, bit_width=BIT_WIDTH)
    index.add_with_ids(vecs, np.asarray(ids, dtype=np.uint64))

    index_path, meta_path = _paths(repo_path)
    index.write(index_path)
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    return len(ids)


def search_entities(repo_path: str, query: str, limit: int = 10) -> dict:
    """Semantic search over entity names/kinds/files/descriptions."""
    np, _, IdMapIndex = _deps()
    index_path, meta_path = _paths(repo_path)
    if not os.path.exists(index_path) or not os.path.exists(meta_path):
        return {"query": query, "matches": [], "count": 0,
                "hint": "No vector index yet — run ingest to build it."}

    vec = np.asarray(list(_embedder().embed([query])), dtype=np.float32)
    index = IdMapIndex.load(index_path)
    with open(meta_path) as f:
        meta = json.load(f)
    scores, ids = index.search(vec, k=limit)

    matches = []
    for score, vid in zip(scores[0].tolist(), ids[0].tolist()):
        payload = meta.get(str(vid))
        if payload is None:  # index/meta out of sync — skip rather than guess
            continue
        matches.append({**payload, "score": round(score, 4)})
    return {"query": query, "matches": matches, "count": len(matches)}
