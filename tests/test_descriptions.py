"""Descriptions live in .codecompass/description.jsonl, joined onto results by
node id — they survive re-ingest and a deleted graph.json, and die with their
node."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import init_project, ingest_code
from graph.code_graph_client import get_client
from ingestion.agent_writes import add_call, add_entity


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


def _description(repo, nid):
    client = get_client(str(repo))
    try:
        return client.describe(nid)
    finally:
        client.close()


def _init(tmp_path, monkeypatch, source):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(source)
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setattr("shutil.which", lambda _: None)  # skip pi/claude extras
    init_project(str(repo))
    ingest_code(str(repo))
    return repo


def test_descriptions_survive_ingest(tmp_path, monkeypatch):
    # dynamic dispatch the parser can't see, so add_call actually adds an edge
    repo = _init(tmp_path, monkeypatch,
                 "def foo():\n    return 1\n\n\ndef bar():\n"
                 "    return globals()['foo']()\n")
    foo_id = _entity_id(repo, "foo")

    add_entity(str(repo), "foo", file="a.py", line=1,
               description="Returns the number one.")

    # the description lands in the sidecar, not on the node
    assert _description(repo, foo_id) == "Returns the number one."
    assert "description" not in _node(repo, foo_id)

    # add an agent_inferred call edge too
    assert add_call(str(repo), "bar", "foo")["status"] in ("added", "exists")

    ingest_code(str(repo))  # old graph replaced by a freshly parsed one

    # same id, so the sidecar still joins onto the freshly parsed node
    assert _description(repo, foo_id) == "Returns the number one."

    client = get_client(str(repo))
    try:
        bar_id = next(nid for nid, a in client.graph.nodes(data=True)
                      if a.get("name") == "bar")
        assert any(e.get("agent_inferred")
                   for e in client.graph.get_edge_data(bar_id, foo_id).values())
    finally:
        client.close()


def test_deleted_entity_takes_its_description_with_it(tmp_path, monkeypatch):
    repo = _init(tmp_path, monkeypatch, "def foo():\n    return 1\n")
    foo_id = _entity_id(repo, "foo")
    add_entity(str(repo), "foo", file="a.py", line=1, description="Returns one.")

    # foo is deleted from source, then re-ingest
    (repo / "a.py").write_text("def baz():\n    return 2\n")
    ingest_code(str(repo))

    client = get_client(str(repo))
    try:
        assert foo_id not in client.graph  # ghost dropped, not resurrected
        assert foo_id not in client.descriptions  # and its description with it
    finally:
        client.close()

    # the pruned sidecar on disk agrees
    assert foo_id not in (repo / ".codecompass" / "description.jsonl").read_text()


def test_descriptions_survive_a_deleted_graph_json(tmp_path, monkeypatch):
    """description.jsonl owns descriptions, so graph.json is disposable."""
    repo = _init(tmp_path, monkeypatch, "def foo():\n    return 1\n")
    foo_id = _entity_id(repo, "foo")
    add_entity(str(repo), "foo", file="a.py", line=1, description="Returns one.")

    sidecar = repo / ".codecompass" / "description.jsonl"
    assert json.loads(sidecar.read_text().splitlines()[0]) == {
        "node": foo_id, "description": "Returns one."}

    # nuke the working index — only the sidecar is left
    (repo / ".codecompass" / "graph.json").unlink()
    ingest_code(str(repo))

    assert _description(repo, foo_id) == "Returns one."

    # and the join reaches the query layer
    from graph.code_queries import fetch_grep
    rows = fetch_grep("foo", str(repo), repo.name)["matches"]
    assert any(r["description"] == "Returns one." for r in rows)


def test_grep_searches_descriptions(tmp_path, monkeypatch):
    repo = _init(tmp_path, monkeypatch, "def foo():\n    return 1\n")
    add_entity(str(repo), "foo", file="a.py", line=1,
               description="Parses the manifest header.")

    from graph.code_queries import fetch_grep
    hits = fetch_grep("manifest", str(repo), repo.name)["matches"]
    assert [h["matched_field"] for h in hits] == ["description"]
    assert hits[0]["name"] == "foo"


def test_failed_ingest_leaves_the_live_graph_alone(tmp_path, monkeypatch):
    """The rebuild happens in graph.json.copy, so a crash mid-parse can't take
    the working graph with it."""
    repo = _init(tmp_path, monkeypatch, "def foo():\n    return 1\n")
    add_entity(str(repo), "foo", file="a.py", line=1, description="Returns one.")
    before = (repo / ".codecompass" / "graph.json").read_text()

    import main as cc_main
    monkeypatch.setattr(cc_main, "parse_directory",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        ingest_code(str(repo))
    except RuntimeError:
        pass

    assert (repo / ".codecompass" / "graph.json").read_text() == before
    assert _description(repo, _entity_id(repo, "foo")) == "Returns one."


def test_agent_created_node_survives_until_its_file_is_deleted(tmp_path, monkeypatch):
    """A node only the agent knows about outlives re-ingest — but not its file."""
    repo = _init(tmp_path, monkeypatch, "def foo():\n    return 1\n")

    r = add_entity(str(repo), "ghost_helper", file="a.py", line=1,
                   description="Helper the parser missed.")
    ghost_id = r["id"]

    ingest_code(str(repo))
    assert _description(repo, ghost_id) == "Helper the parser missed."

    # delete the file the ghost lives in -> ghost is dropped
    (repo / "a.py").unlink()
    ingest_code(str(repo))

    client = get_client(str(repo))
    try:
        assert ghost_id not in client.graph
        assert ghost_id not in client.descriptions  # pruned with its node
    finally:
        client.close()
