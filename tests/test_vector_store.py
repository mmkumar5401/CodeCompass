"""Vector store: wipe-rebuild on index + semantic search returns the right entity.

Uses real turbovec in a tmp dir; the embedding model is faked with a
bag-of-words hash so the test needs no download. Skips when the optional
`search` deps aren't installed.
"""

import json

import pytest

pytest.importorskip("turbovec")
pytest.importorskip("fastembed")

from graph import vector_store

# conftest stubs index_entities suite-wide (ingest builds vectors by default);
# these tests exercise the REAL one.
_real_index_entities = vector_store.index_entities


class _FakeEmbedder:
    # **kwargs mirrors fastembed's embed(texts, batch_size=..., parallel=...)
    def embed(self, texts, **kwargs):
        vecs = []
        for t in texts:
            v = [0.0] * 384
            for word in t.lower().split():
                v[hash(word) % 384] += 1.0
            vecs.append(v)
        return iter(vecs)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(vector_store, "index_entities", _real_index_entities)
    monkeypatch.setattr(vector_store, "_embedder", lambda: _FakeEmbedder())
    cc = tmp_path / ".codecompass"
    cc.mkdir()
    graph = {
        "nodes": [
            {"type": "Entity", "id": "p:a.py:session_handler", "name": "session_handler",
             "kind": "function:python", "file": "a.py", "line": 3,
             "description": "handles session timeout"},
            {"type": "Entity", "id": "p:b.py:render_button", "name": "render_button",
             "kind": "function:python", "file": "b.py", "line": 1,
             "description": ""},
            {"type": "File", "id": "p:a.py", "path": "a.py"},  # not indexed
        ],
        "links": [],
    }
    (cc / "graph.json").write_text(json.dumps(graph))
    return str(tmp_path)


def test_index_skips_non_entities(repo):
    assert vector_store.index_entities(repo) == 2


def test_search_finds_by_description(repo):
    vector_store.index_entities(repo)
    hits = vector_store.search_entities(repo, "session timeout")
    assert hits["count"] >= 1
    assert hits["matches"][0]["name"] == "session_handler"


def test_embed_many_preserves_input_order(monkeypatch):
    """_embed_many sorts by length internally — vectors must come back unsorted.

    Guards the mapping between vectors and node ids: if the unsort is wrong
    every search result silently points at the wrong entity.
    """
    monkeypatch.setattr(vector_store, "_embedder", lambda: _FakeEmbedder())
    fake = _FakeEmbedder()
    # deliberately unsorted lengths, so a missing unsort would reorder them
    texts = ["zzz", "b" * 200, "mid length text", "a", "c" * 50]

    got = vector_store._embed_many(texts)

    assert len(got) == len(texts)
    for i, text in enumerate(texts):
        expected = next(iter(fake.embed([text])))
        assert got[i].tolist() == pytest.approx(expected), f"row {i} ({text[:12]!r})"


def test_reindex_invalidates_cached_index(repo):
    """The loaded index is cached per process — a re-ingest must not serve stale hits.

    Guards the mtime cache key in _load_index: if it stopped changing, search
    would keep answering from the pre-ingest index (silently, forever).
    """
    vector_store.index_entities(repo)
    assert vector_store.search_entities(repo, "session timeout")["count"] == 2

    graph_path = f"{repo}/.codecompass/graph.json"
    graph = json.loads(open(graph_path).read())
    graph["nodes"] = [
        n for n in graph["nodes"] if n.get("name") != "render_button"
    ] + [
        {"type": "Entity", "id": "p:c.py:audit_log", "name": "audit_log",
         "kind": "function:python", "file": "c.py", "line": 7,
         "description": "writes audit trail entries"},
    ]
    open(graph_path, "w").write(json.dumps(graph))
    vector_store.index_entities(repo)

    names = {m["name"] for m in
             vector_store.search_entities(repo, "audit trail", limit=10)["matches"]}
    assert "audit_log" in names, "new entity missing — cache served a stale index"
    assert "render_button" not in names, "deleted entity still returned"


def test_search_without_index_reports_hint(tmp_path):
    (tmp_path / ".codecompass").mkdir()
    out = vector_store.search_entities(str(tmp_path), "anything")
    assert out["count"] == 0
    assert "hint" in out
