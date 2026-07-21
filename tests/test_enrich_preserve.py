"""Enrich-written descriptions and agent_inferred nodes/edges survive re-ingest."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import init_project, ingest_code
from graph.code_graph_client import get_client
from ingestion.enricher import apply_enrich_results, add_call


def _entity_id(repo, name):
    client = get_client(str(repo))
    try:
        return next(nid for nid, a in client.graph.nodes(data=True)
                    if a.get("type") == "Entity" and a.get("name") == name)
    finally:
        client.close()


def _node(repo, nid):
    client = get_client(str(repo))
    try:
        return dict(client.graph.nodes[nid])
    finally:
        client.close()


def test_enrich_descriptions_survive_ingest(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    # dynamic dispatch the parser can't see, so add_call actually adds an edge
    (repo / "a.py").write_text(
        "def foo():\n    return 1\n\n\ndef bar():\n    return globals()['foo']()\n")
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setattr("shutil.which", lambda _: None)  # skip pi/claude extras

    init_project(str(repo))
    ingest_code(str(repo))

    foo_id = _entity_id(repo, "foo")

    # simulate an enrich result and apply it
    enrich_dir = repo / ".codecompass" / "enrich"
    enrich_dir.mkdir()
    (enrich_dir / "batch_0000.result.json").write_text(json.dumps({
        foo_id: {"description": "Returns the number one.", "missing_calls": []},
    }))
    stats = apply_enrich_results(str(repo))
    assert stats["descriptions"] == 1

    # enrich marks the node agent_inferred
    node = _node(repo, foo_id)
    assert node["description"] == "Returns the number one."
    assert node["agent_inferred"] is True

    # add an agent_inferred call edge too
    r = add_call(str(repo), "bar", "foo")
    assert r["status"] in ("added", "exists")

    # re-ingest: old graph replaced by a freshly parsed one
    ingest_code(str(repo))

    # same id, description carried over, still marked agent_inferred
    node = _node(repo, foo_id)
    assert node["description"] == "Returns the number one."
    assert node["agent_inferred"] is True

    # agent_inferred edge survived
    client = get_client(str(repo))
    try:
        bar_id = next(nid for nid, a in client.graph.nodes(data=True)
                      if a.get("name") == "bar")
        assert any(e.get("agent_inferred")
                   for e in client.graph.get_edge_data(bar_id, foo_id).values())
    finally:
        client.close()


def test_deleted_entity_is_not_resurrected(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n")
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setattr("shutil.which", lambda _: None)

    init_project(str(repo))
    ingest_code(str(repo))
    foo_id = _entity_id(repo, "foo")

    enrich_dir = repo / ".codecompass" / "enrich"
    enrich_dir.mkdir()
    (enrich_dir / "batch_0000.result.json").write_text(json.dumps({
        foo_id: {"description": "Returns one.", "missing_calls": []},
    }))
    apply_enrich_results(str(repo))

    # foo is deleted from source, then re-ingest
    (repo / "a.py").write_text("def baz():\n    return 2\n")
    ingest_code(str(repo))

    client = get_client(str(repo))
    try:
        assert foo_id not in client.graph  # ghost dropped, not resurrected
    finally:
        client.close()


def test_agent_created_node_survives_until_its_file_is_deleted(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n")
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setattr("shutil.which", lambda _: None)

    init_project(str(repo))
    ingest_code(str(repo))

    from ingestion.enricher import add_entity
    r = add_entity(str(repo), "ghost_helper", file="a.py", line=1,
                   description="Helper the parser missed.")
    ghost_id = r["id"]

    ingest_code(str(repo))
    assert _node(repo, ghost_id)["description"] == "Helper the parser missed."

    # delete the file the ghost lives in -> ghost is dropped
    (repo / "a.py").unlink()
    ingest_code(str(repo))

    client = get_client(str(repo))
    try:
        assert ghost_id not in client.graph
    finally:
        client.close()
