import json

import pytest

from graph.code_graph_client import get_client
from ingestion.description_enricher import apply_describe_results, prepare_describe_batches
from models.code_types import FileNode


def _seed_entity(repo_path, project, entity_id, name="greet"):
    src_dir = repo_path / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "greet.py").write_text('def greet(name):\n    return f"Hello {name}"\n')

    client = get_client(str(repo_path))
    client.merge_project_node(f"{project}:project", project, str(repo_path))
    file_node = FileNode(path="src/greet.py", name="greet.py", extension=".py", depth=1)
    client.merge_file_node(f"{project}:file:src/greet.py", file_node, project)
    client.graph.add_node(
        entity_id,
        type="Entity",
        name=name,
        kind="function:python",
        entity_type="function",
        language="python",
        file="src/greet.py",
        project=project,
        description="old generic description",
    )
    client.save()
    client.close()


def test_prepare_describe_batches_writes_batch_and_instructions(tmp_path):
    project = "demo"
    repo_path = tmp_path / project
    repo_path.mkdir()
    entity_id = f"{project}:greet"
    _seed_entity(repo_path, project, entity_id)

    staged = prepare_describe_batches(str(repo_path), batch_size=15)

    assert staged["num_entities"] == 1
    assert staged["num_batches"] == 1
    describe_dir = repo_path / ".codecompass" / "describe"
    assert (describe_dir / "batch_0000.json").exists()
    assert (describe_dir / "INSTRUCTIONS.md").exists()

    batch = json.loads((describe_dir / "batch_0000.json").read_text())
    assert batch[0]["id"] == entity_id
    assert batch[0]["name"] == "greet"


def test_prepare_describe_batches_noop_when_nothing_to_describe(tmp_path):
    project = "empty"
    repo_path = tmp_path / project
    repo_path.mkdir()
    client = get_client(str(repo_path))
    client.merge_project_node(f"{project}:project", project, str(repo_path))
    client.save()
    client.close()

    staged = prepare_describe_batches(str(repo_path))

    assert staged["num_entities"] == 0
    assert not (repo_path / ".codecompass" / "describe").exists()


def test_apply_describe_results_updates_nodes_and_cleans_up(tmp_path):
    project = "demo"
    repo_path = tmp_path / project
    repo_path.mkdir()
    entity_id = f"{project}:greet"
    _seed_entity(repo_path, project, entity_id)

    staged = prepare_describe_batches(str(repo_path), batch_size=15)
    describe_dir = repo_path / ".codecompass" / "describe"
    result_path = describe_dir / "batch_0000.result.json"
    result_path.write_text(json.dumps({entity_id: "Greets a user by name."}))

    updated = apply_describe_results(str(repo_path))
    assert updated == 1

    client = get_client(str(repo_path))
    assert client.graph.nodes[entity_id]["description"] == "Greets a user by name."
    client.close()

    assert not describe_dir.exists()


def test_apply_describe_results_without_staged_batches_raises(tmp_path):
    repo_path = tmp_path / "nothing-staged"
    repo_path.mkdir()
    with pytest.raises(FileNotFoundError, match="No staged description batches"):
        apply_describe_results(str(repo_path))
