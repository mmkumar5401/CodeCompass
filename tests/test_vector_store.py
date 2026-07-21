"""Vector store: wipe-rebuild on index + semantic search returns the right entity.

Uses real LanceDB in a tmp dir; the embedding model is faked with a
bag-of-words hash so the test needs no download. Skips when the optional
`search` deps aren't installed.
"""

import json

import pytest

pytest.importorskip("lancedb")
pytest.importorskip("fastembed")

from graph import vector_store


class _FakeEmbedder:
    def embed(self, texts):
        vecs = []
        for t in texts:
            v = [0.0] * 384
            for word in t.lower().split():
                v[hash(word) % 384] += 1.0
            vecs.append(v)
        return iter(vecs)


@pytest.fixture
def repo(tmp_path, monkeypatch):
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


def test_search_without_index_reports_hint(tmp_path):
    (tmp_path / ".codecompass").mkdir()
    out = vector_store.search_entities(str(tmp_path), "anything")
    assert out["count"] == 0
    assert "hint" in out
