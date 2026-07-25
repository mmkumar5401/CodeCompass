"""Agent writes: add_entity/add_call populate the graph, descriptions land on
the nodes, delete_entity/delete_call undo them, ambiguous names are skipped,
and all of it survives a re-ingest."""

from graph.code_graph_client import get_client
from ingestion.agent_writes import add_call, add_entity, delete_call, delete_entity
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
    # flagged because the parser never produced it: the ingest join re-adds it
    assert node["line"] == 9 and node["agent_created"] is True
    # the description is a plain node attribute
    assert node["description"] == "Async helper."
    assert client.describe(r["id"]) == "Async helper."
    client.close()
    # Upsert: same name+file updates instead of duplicating; a blank description
    # on update keeps the recorded one rather than clearing it
    r = add_entity(str(repo_path), "helper", file="src/a.py")
    assert r["status"] == "updated"
    client = get_client(str(repo_path))
    assert client.describe(r["id"]) == "Async helper."
    client.close()
    # No description given, none invented — an undescribed entity reads as ""
    r2 = add_entity(str(repo_path), "bare", file="src/a.py")
    client = get_client(str(repo_path))
    assert client.describe(r2["id"]) == ""
    client.close()

    # Parser-missed edge: resolvable -> added once, then idempotent
    assert add_call(str(repo_path), "caller", "callee", line=2)["status"] == "added"
    assert add_call(str(repo_path), "caller", "callee")["status"] == "exists"
    # Ambiguous names return the candidates so the caller can retry precisely
    out = add_call(str(repo_path), "caller", "shared")
    assert out["status"] == "ambiguous" and len(out["candidates"]) == 2
    assert add_call(str(repo_path), "caller", "shared",
                    caller_file="", callee_file="src/b.py")["status"] == "added"
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
                    relation="IMPORTS")["status"] == "ambiguous"

    client = get_client(str(repo_path))
    helper_id = next(n for n, a in client.graph.nodes(data=True) if a.get("name") == "helper")
    assert client.describe(helper_id) == "Async helper."
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


def test_describing_a_parser_node_claims_no_ownership(tmp_path):
    """add_entity on an entity the parser already produces must not flag it —
    that would resurrect the symbol on every ingest after it's deleted."""
    project = "demo"
    repo_path = tmp_path / project
    repo_path.mkdir()
    _seed(repo_path, project)

    add_entity(str(repo_path), "caller", file="src/a.py", description="Entry point.")

    client = get_client(str(repo_path))
    assert "agent_created" not in client.graph.nodes[f"{project}:caller"]
    assert client.describe(f"{project}:caller") == "Entry point."
    client.close()


def test_agent_data_survives_reingest(tmp_path):
    """The parse is authoritative for parser-visible code, but the join carries
    over what only the agent knows: its nodes, edges, and descriptions."""
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
    # The agent's CALLS edge joins back on: both ends still exist in source.
    agent_edges = [(u, v) for u, v, e in client.graph.edges(data=True)
                   if e.get("type") == "CALLS" and e.get("agent_inferred")]
    assert len(agent_edges) == 1
    names = {client.graph.nodes[n].get("name") for n in agent_edges[0]}
    assert names == {"caller", "target"}
    # The node the parser can't see, and its description, are carried over
    helper_id = next(n for n, a in client.graph.nodes(data=True) if a.get("name") == "helper")
    assert client.graph.nodes[helper_id]["agent_created"] is True
    assert client.describe(helper_id) == "Async helper."
    # The file-less stdlib node and its IMPORTS edge survive too
    assert client.graph.nodes[f"{project}:pathlib"]["agent_created"] is True
    assert any(e.get("type") == "IMPORTS" and e.get("agent_inferred")
               for _, _, e in client.graph.edges(data=True))
    client.close()


def test_delete_entity_removes_agent_created_node(tmp_path):
    repo_path = tmp_path / "demo"
    _seed(repo_path, "demo")

    r = add_entity(str(repo_path), "ghost", file="src/a.py", description="Phantom.")
    out = delete_entity(str(repo_path), "ghost")
    assert out["status"] == "deleted" and out["id"] == r["id"]

    client = get_client(str(repo_path))
    assert r["id"] not in client.graph
    client.close()


def test_delete_entity_strips_parser_node_but_keeps_it(tmp_path):
    repo_path = tmp_path / "demo"
    _seed(repo_path, "demo")
    callee_id = "demo:callee"

    add_entity(str(repo_path), "callee", file="src/a.py", description="Agent note.")
    add_call(str(repo_path), "caller", "callee")
    out = delete_entity(str(repo_path), "callee")
    assert out["status"] == "stripped"

    client = get_client(str(repo_path))
    assert callee_id in client.graph  # parser-owned — kept
    assert client.describe(callee_id) == ""
    assert not any(e.get("agent_inferred")
                   for _, _, e in client.graph.edges(data=True))
    client.close()


def test_delete_entity_ambiguous_and_missing(tmp_path):
    repo_path = tmp_path / "demo"
    _seed(repo_path, "demo")

    out = delete_entity(str(repo_path), "shared")
    assert out["status"] == "ambiguous" and len(out["candidates"]) == 2
    assert delete_entity(str(repo_path), "shared", file="src/b.py")["status"] in (
        "stripped", "deleted")
    assert delete_entity(str(repo_path), "nonexistent")["status"] == "not_found"


def test_delete_call_removes_only_agent_edges(tmp_path):
    repo_path = tmp_path / "demo"
    _seed(repo_path, "demo")

    assert add_call(str(repo_path), "caller", "callee")["status"] == "added"
    out = delete_call(str(repo_path), "caller", "callee")
    assert out["status"] == "removed"
    # second delete: nothing left
    assert delete_call(str(repo_path), "caller", "callee")["status"] == "not_found"
    # parser-owned CALLS (caller->callee was seeded in source? no — seed only
    # adds nodes, so add a parser-style edge explicitly)
    client = get_client(str(repo_path))
    client.graph.add_edge("demo:caller", "demo:callee", type="CALLS", resolved=True)
    client.save()
    client.close()
    assert delete_call(str(repo_path), "caller", "callee")["status"] == "skipped"
    # IMPORTS round-trip
    assert add_call(str(repo_path), "caller", "pathlib",
                    relation="IMPORTS")["status"] == "added"
    assert delete_call(str(repo_path), "caller", "pathlib",
                       relation="IMPORTS")["status"] == "removed"


def test_deleted_agent_node_does_not_come_back_on_ingest(tmp_path):
    repo_path = tmp_path / "demo"
    src = repo_path / "src"
    src.mkdir(parents=True)
    (src / "a.py").write_text("def caller():\n    return 1\n")

    import main as cc_main
    cc_main.ingest_code(str(repo_path))

    r = add_entity(str(repo_path), "ghost", file="src/a.py", description="Phantom.")
    assert delete_entity(str(repo_path), "ghost")["status"] == "deleted"

    cc_main.ingest_code(str(repo_path))
    client = get_client(str(repo_path))
    assert r["id"] not in client.graph
    client.close()


def test_free_form_relations(tmp_path):
    repo_path = tmp_path / "demo"
    _seed(repo_path, "demo")

    assert add_call(str(repo_path), "caller", "callee",
                    relation="listens to")["status"] == "added"
    client = get_client(str(repo_path))
    types = {e.get("type") for e in
             client.graph.get_edge_data("demo:caller", "demo:callee").values()}
    assert "LISTENS_TO" in types
    client.close()
    # parser-owned structural relations are still refused
    assert add_call(str(repo_path), "caller", "callee",
                    relation="DEFINED_IN")["status"] == "skipped"


def test_modify_relation_retypes_and_wins_over_parser_on_ingest(tmp_path):
    repo_path = tmp_path / "demo"
    src = repo_path / "src"
    src.mkdir(parents=True)
    (src / "a.py").write_text(
        "class Base:\n    pass\n\n\nclass Child(Base):\n    pass\n")

    import main as cc_main
    from ingestion.agent_writes import modify_relation
    cc_main.ingest_code(str(repo_path))

    client = get_client(str(repo_path))
    child_id = next(n for n, a in client.graph.nodes(data=True) if a.get("name") == "Child")
    base_id = next(n for n, a in client.graph.nodes(data=True) if a.get("name") == "Base")
    assert any(e.get("type") == "INHERITS"
               for e in client.graph.get_edge_data(child_id, base_id, default={}).values())
    client.close()

    # parser says INHERITS; agent retypes it to something else
    out = modify_relation(str(repo_path), "Child", "Base", to_relation="registers")
    assert out["status"] == "modified" and out["to_relation"] == "REGISTERS"

    client = get_client(str(repo_path))
    types = {e.get("type") for e in client.graph.get_edge_data(child_id, base_id).values()}
    assert types == {"REGISTERS"}
    client.close()

    # re-ingest: the parser re-derives INHERITS, but the agent's relation wins
    cc_main.ingest_code(str(repo_path))
    client = get_client(str(repo_path))
    edges = client.graph.get_edge_data(child_id, base_id, default={})
    types = {e.get("type") for e in edges.values()}
    assert types == {"REGISTERS"}
    assert any(e.get("agent_relation") for e in edges.values())
    client.close()


def test_modify_relation_not_found_and_ambiguous(tmp_path):
    repo_path = tmp_path / "demo"
    _seed(repo_path, "demo")
    from ingestion.agent_writes import modify_relation

    assert modify_relation(str(repo_path), "caller", "callee",
                           to_relation="CALLS")["status"] == "not_found"
    out = modify_relation(str(repo_path), "caller", "shared", to_relation="CALLS")
    assert out["status"] == "ambiguous" and out["side"] == "callee"
    # structural targets refused
    assert modify_relation(str(repo_path), "caller", "callee",
                           to_relation="CONTAINS")["status"] == "skipped"
