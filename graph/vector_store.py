"""Local vector search over graph entities — LanceDB + fastembed.

Optional feature: needs `pip install codecompass-mcp[search]`.
The index lives at `.codecompass/vectors.lance` and follows the graph's
lifecycle: wiped and rebuilt wholesale at the end of every ingest, from
whatever the graph contains at that point (parser + agent-inferred nodes).

ponytail: full rebuild each ingest (no per-file incremental updates) — a few
thousand short embeddings take seconds; add incremental indexing only if
ingest time actually hurts.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

DB_DIRNAME = "vectors.lance"
TABLE = "entities"
MODEL = "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX, CPU — no torch, no network calls


class VectorDepsMissing(RuntimeError):
    """Raised when lancedb/fastembed aren't installed."""


def _deps():
    try:
        import lancedb
        from fastembed import TextEmbedding
        return lancedb, TextEmbedding
    except ImportError as exc:
        raise VectorDepsMissing(
            "Vector search needs the optional deps: "
            "pip install 'codecompass-mcp[search]'"
        ) from exc


@lru_cache(maxsize=1)
def _embedder():
    _, TextEmbedding = _deps()
    return TextEmbedding(model_name=MODEL)


def _db_path(repo_path: str) -> str:
    return os.path.join(repo_path, ".codecompass", DB_DIRNAME)


def _entity_text(a: dict) -> str:
    """The string that gets embedded for one entity node."""
    parts = [a.get("kind") or "", a.get("name") or "", a.get("file") or "",
             a.get("description") or ""]
    return " ".join(p for p in parts if p)


def index_entities(repo_path: str) -> int:
    """Wipe and rebuild the vector index from graph.json. Returns rows indexed."""
    lancedb, _ = _deps()
    graph_path = os.path.join(repo_path, ".codecompass", "graph.json")
    with open(graph_path) as f:
        nodes = json.load(f).get("nodes", [])

    rows = []
    for a in nodes:
        if a.get("type") != "Entity":
            continue
        rows.append({
            "id": a.get("id") or "",
            "name": a.get("name") or "",
            "kind": a.get("kind") or "",
            "file": a.get("file") or "",
            "line": a.get("line") or 0,
            "description": a.get("description") or "",
            "text": _entity_text(a),
        })
    if not rows:
        return 0

    vecs = list(_embedder().embed([r["text"] for r in rows]))
    for r, v in zip(rows, vecs):
        r["vector"] = v

    db = lancedb.connect(_db_path(repo_path))
    db.create_table(TABLE, rows, mode="overwrite")
    return len(rows)


def search_entities(repo_path: str, query: str, limit: int = 10) -> dict:
    """Semantic search over entity names/kinds/files/descriptions."""
    lancedb, _ = _deps()
    db_path = _db_path(repo_path)
    if not os.path.exists(db_path):
        return {"query": query, "matches": [], "count": 0,
                "hint": "No vector index yet — run ingest to build it."}

    vec = list(_embedder().embed([query]))[0]
    db = lancedb.connect(db_path)
    tbl = db.open_table(TABLE)
    hits = tbl.search(vec).limit(limit).to_list()

    matches = [{
        "name": h["name"],
        "kind": h["kind"],
        "file": h["file"],
        "line": h["line"],
        "description": h["description"],
        "distance": round(h["_distance"], 4),
    } for h in hits]
    return {"query": query, "matches": matches, "count": len(matches)}
