"""Enrich staging/apply: descriptions merge, unambiguous missing calls become
agent_inferred CALLS edges, ambiguous names are skipped."""

import json

from graph.code_graph_client import get_client
from ingestion.enricher import (add_call, add_entity, apply_enrich_results,
                                prepare_enrich_batches)
from models.code_types import FileNode


def _seed(repo_path, project):
    src = repo_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.py").write_text("def caller():\n    return callee()\n")
    client = get_client(str(repo_path))
    client.merge_project_node(f"{project}:project", project, str(repo_path))
    client.merge_file_node(f"{project}:file:src/a.py",
                           FileNode(path="src/a.py", name="a.py", extension=".py", depth=1),
                           project)
    for name in ("caller", "callee"):
        client.graph.add_node(
            f"{project}:{name}",
            type="Entity", name=name, kind="function:python",
            entity_type="function", language="python",
            file="src/a.py", project=project, line=1,
            description=f"python function in src/a.py",
        )
    # Two same-named entities in other files -> ambiguous resolution target
    for f in ("src/b.py", "src/c.py"):
        client.graph.add_node(
            f"{project}:shared:{f}",
            type="Entity", name="shared", kind="function:python",
            entity_type="function", language="python",
            file=f, project=project, line=1,
        )
    client.save()
    client.close()


def test_enrich_stage_and_apply(tmp_path):
    project = "demo"
    repo_path = tmp_path / project
    repo_path.mkdir()
    _seed(repo_path, project)

    staged = prepare_enrich_batches(str(repo_path))
    assert staged["num_entities"] == 4
    enrich_dir = repo_path / ".codecompass" / "enrich"
    batch = json.loads((enrich_dir / "batch_0000.json").read_text())
    caller = next(p for p in batch if p["name"] == "caller")
    assert caller["known_callees"] == [] and caller["snippet"]

    # Fake the sub-agent's result: description + one resolvable + one
    # ambiguous missing call.
    result = {
        f"{project}:caller": {
            "description": "Entry point that delegates to callee.",
            "missing_calls": [{"to": "callee", "line": 2}, {"to": "shared"}],
        }
    }
    (enrich_dir / "batch_0000.result.json").write_text(json.dumps(result))

    stats = apply_enrich_results(str(repo_path))
    assert stats == {"descriptions": 1, "edges_added": 1, "calls_skipped": 1}

    client = get_client(str(repo_path))
    node = client.graph.nodes[f"{project}:caller"]
    assert node["description"] == "Entry point that delegates to callee."
    edges = client.graph.get_edge_data(f"{project}:caller", f"{project}:callee")
    edge = next(e for e in edges.values() if e.get("type") == "CALLS")
    assert edge["agent_inferred"] is True and edge["line"] == 2
    client.close()
    assert not enrich_dir.exists()  # cleaned up


def test_add_entity_and_add_call(tmp_path):
    project = "demo"
    repo_path = tmp_path / project
    repo_path.mkdir()
    _seed(repo_path, project)

    # New entity the parser missed — all fields populated, language inferred
    r = add_entity(str(repo_path), "helper", kind="function",
                   file="src/a.py", line=9, description="Async helper.")
    assert r["status"] == "created"
    client = get_client(str(repo_path))
    node = client.graph.nodes[r["id"]]
    assert node["language"] == "python" and node["kind"] == "function:python"
    assert node["line"] == 9 and node["agent_inferred"] is True
    client.close()
    # Upsert: same name+file updates instead of duplicating; a field left
    # blank on update keeps the previous value (no clobbering with fallback)
    r = add_entity(str(repo_path), "helper", file="src/a.py")
    assert r["status"] == "updated"
    client = get_client(str(repo_path))
    assert client.graph.nodes[r["id"]]["description"] == "Async helper."
    client.close()
    # Fallback description when the agent gives none
    r2 = add_entity(str(repo_path), "bare", file="src/a.py")
    client = get_client(str(repo_path))
    assert client.graph.nodes[r2["id"]]["description"] == "python function in src/a.py"
    client.close()

    # Parser-missed edge: resolvable -> added once, then idempotent
    assert add_call(str(repo_path), "caller", "callee", line=2)["status"] == "added"
    assert add_call(str(repo_path), "caller", "callee")["status"] == "exists"
    # Ambiguous / unknown names are skipped, never guessed
    assert add_call(str(repo_path), "caller", "shared")["status"] == "skipped"
    assert add_call(str(repo_path), "ghost", "callee")["status"] == "skipped"

    # Non-CALLS relations ride the same tool; CALLS on the same pair already
    # exists, so a distinct type must still be added.
    assert add_call(str(repo_path), "caller", "callee",
                    relation="imports")["status"] == "added"
    assert add_call(str(repo_path), "caller", "callee",
                    relation="IMPORTS")["status"] == "exists"
    # Structural edges stay parser-owned
    assert add_call(str(repo_path), "caller", "callee",
                    relation="CONTAINS")["status"] == "skipped"

    # IMPORTS of a module the graph has never seen creates the external node;
    # a CALLS to the same unknown name still skips (only imports go external).
    assert add_call(str(repo_path), "caller", "pathlib",
                    relation="IMPORTS")["status"] == "added"
    assert add_call(str(repo_path), "caller", "pathlib")["status"] == "skipped"
    # Ambiguity still wins over node creation
    assert add_call(str(repo_path), "caller", "shared",
                    relation="IMPORTS")["status"] == "skipped"

    client = get_client(str(repo_path))
    node = next(a for _, a in client.graph.nodes(data=True) if a.get("name") == "helper")
    assert node["description"] == "Async helper." and node["agent_inferred"] is True
    edge = next(e for e in client.graph.get_edge_data(
        f"{project}:caller", f"{project}:callee").values() if e.get("type") == "CALLS")
    assert edge["agent_inferred"] is True
    imports = next(e for e in client.graph.get_edge_data(
        f"{project}:caller", f"{project}:callee").values() if e.get("type") == "IMPORTS")
    assert imports["agent_inferred"] is True
    # The stdlib module node the agent created: file-less, like the parser's own
    stdlib = client.graph.nodes[f"{project}:pathlib"]
    assert stdlib["kind"] == "module:python" and not stdlib.get("file")
    assert stdlib["agent_created"] is True
    client.close()


def test_agent_data_survives_reingest(tmp_path):
    """Full ingest clears the graph; agent_inferred nodes/edges/descriptions
    must be preserved across the rebuild."""
    project = "demo"
    repo_path = tmp_path / project
    repo_path.mkdir()
    src = repo_path / "src"
    src.mkdir(parents=True)
    # caller and target are both parser-visible, but nothing calls target —
    # so any caller->target edge can only come from the agent.
    (src / "a.py").write_text(
        "def caller():\n    return 1\n\ndef target():\n    return 2\n")

    import main as cc_main
    cc_main.ingest_code(str(repo_path))  # parser-only graph

    add_entity(str(repo_path), "helper", file="src/a.py", description="Async helper.")
    assert add_call(str(repo_path), "caller", "target", line=2)["status"] == "added"
    assert add_call(str(repo_path), "caller", "pathlib",
                    relation="IMPORTS")["status"] == "added"

    cc_main.ingest_code(str(repo_path))  # full rebuild

    client = get_client(str(repo_path))
    helper = next(a for _, a in client.graph.nodes(data=True) if a.get("name") == "helper")
    assert helper["agent_inferred"] is True and helper["description"] == "Async helper."
    agent_edges = [(u, v) for u, v, e in client.graph.edges(data=True)
                   if e.get("type") == "CALLS" and e.get("agent_inferred")]
    assert len(agent_edges) == 1
    names = {client.graph.nodes[n].get("name") for n in agent_edges[0]}
    assert names == {"caller", "target"}
    # The file-less stdlib node and its IMPORTS edge survive too
    assert client.graph.nodes[f"{project}:pathlib"]["agent_created"] is True
    assert any(e.get("type") == "IMPORTS" and e.get("agent_inferred")
               for _, _, e in client.graph.edges(data=True))
    client.close()
