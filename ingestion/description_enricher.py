"""Description enrichment for the code knowledge graph — agent-swarm edition.

Tree-sitter gives us structure; this pass fills in the meaning. Rather than
calling any single vendor's API directly, it stages the work as plain files
and hands control back to whichever coding agent is driving the CLI (Claude
Code, Codex, Gemini, or anything else). That agent dispatches its own native
sub-agents — one per batch — to write descriptions, then `describe --apply`
merges the results into the graph. No API key, no vendor lock-in.
"""

from __future__ import annotations

import json
import os
from typing import Any

from graph.code_graph_client import get_client
from ingestion.source_context import extract_entity_context

DEFAULT_BATCH_SIZE = 15
DESCRIBE_SUBDIR = os.path.join(".codecompass", "describe")

_INSTRUCTIONS_TEMPLATE = """\
# Description enrichment — agent swarm task

{num_entities} entities across {num_batches} batch file(s) in this directory
need a one-sentence description written for the code knowledge graph.

## What to do

1. For each `batch_XXXX.json` file here, dispatch one sub-agent (in parallel).
   Give each sub-agent this task:

   > Read `{describe_dir}/batch_XXXX.json`. It is a JSON list of entities,
   > each with `id`, `name`, `kind`, `file`, `signature`, `docstring`, and
   > `snippet`. For every entity, write ONE clear sentence describing what
   > it does or its role in the codebase. If signature/docstring/snippet are
   > empty, infer a sensible description from the name, kind, and file path.
   > Write the result to `{describe_dir}/batch_XXXX.result.json` as a JSON
   > object mapping each entity's `id` to its description string. Output
   > nothing else — no markdown fences, no commentary, just the file.

2. Once every `batch_XXXX.result.json` file exists, run:

   ```
   codecompass describe {repo_path} --apply
   ```

   This merges every result file into the graph and cleans up this directory.

## Batches

{batch_list}
"""


def _entity_context(repo_path: str, node_id: str, attr: dict[str, Any]) -> dict[str, Any]:
    """Build the sub-agent payload for a single entity."""
    name = attr.get("name", "")
    file = attr.get("file", "")
    ctx = extract_entity_context(repo_path, file, name) if file else {}
    return {
        "id": node_id,
        "name": name,
        "kind": attr.get("kind", ""),
        "file": file,
        "signature": ctx.get("signature", ""),
        "docstring": ctx.get("docstring", ""),
        "snippet": ctx.get("snippet", ""),
    }


def _describe_dir(repo_path: str) -> str:
    return os.path.join(os.path.abspath(repo_path), DESCRIBE_SUBDIR)


def prepare_describe_batches(
    repo_path: str, batch_size: int = DEFAULT_BATCH_SIZE, force: bool = False
) -> dict[str, Any]:
    """Stage entities needing descriptions into batch files plus an instructions doc.

    Returns {"num_entities", "num_batches", "describe_dir", "instructions_path"}.
    Writing no batches (num_entities == 0) leaves no files behind.

    Raises RuntimeError if a previous run already has result files staged —
    re-running would silently discard that in-progress work. Pass force=True
    to overwrite anyway.
    """
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    describe_dir = _describe_dir(repo_path)

    if not force and os.path.isdir(describe_dir):
        existing_results = [f for f in os.listdir(describe_dir) if f.endswith(".result.json")]
        if existing_results:
            raise RuntimeError(
                f"{len(existing_results)} result file(s) already staged at {describe_dir} "
                "from a previous describe run. Run `codecompass describe "
                f"{repo_path} --apply` to finish it first, or re-run with force=True "
                "to discard them and restage."
            )

    client = get_client(repo_path)
    try:
        entities = [
            (node_id, attr)
            for node_id, attr in client.graph.nodes(data=True)
            if attr.get("type") == "Entity"
            and attr.get("project") == project
            and attr.get("file")
        ]
    finally:
        client.close()

    result = {
        "num_entities": len(entities),
        "num_batches": 0,
        "describe_dir": describe_dir,
        "instructions_path": None,
    }
    if not entities:
        return result

    os.makedirs(describe_dir, exist_ok=True)

    batches = [entities[i : i + batch_size] for i in range(0, len(entities), batch_size)]
    batch_names = []
    for idx, batch in enumerate(batches):
        batch_name = f"batch_{idx:04d}.json"
        payload = [_entity_context(repo_path, node_id, attr) for node_id, attr in batch]
        with open(os.path.join(describe_dir, batch_name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        batch_names.append(batch_name)

    instructions_path = os.path.join(describe_dir, "INSTRUCTIONS.md")
    with open(instructions_path, "w", encoding="utf-8") as f:
        f.write(
            _INSTRUCTIONS_TEMPLATE.format(
                num_entities=len(entities),
                num_batches=len(batches),
                describe_dir=describe_dir,
                repo_path=repo_path,
                batch_list="\n".join(f"- {name}" for name in batch_names),
            )
        )

    result["num_batches"] = len(batches)
    result["instructions_path"] = instructions_path
    return result


def apply_describe_results(repo_path: str) -> int:
    """Merge every `batch_*.result.json` file into the graph and clean up.

    Returns the number of nodes updated. Raises FileNotFoundError if no
    staged batch directory exists (nothing to apply).
    """
    repo_path = os.path.abspath(repo_path)
    describe_dir = _describe_dir(repo_path)
    if not os.path.isdir(describe_dir):
        raise FileNotFoundError(
            f"No staged description batches found at {describe_dir}. "
            "Run `codecompass describe <repo_path>` first."
        )

    descriptions: dict[str, str] = {}
    result_files = sorted(f for f in os.listdir(describe_dir) if f.endswith(".result.json"))
    for name in result_files:
        with open(os.path.join(describe_dir, name), encoding="utf-8") as f:
            try:
                descriptions.update(json.load(f))
            except json.JSONDecodeError:
                continue

    client = get_client(repo_path)
    try:
        updated = 0
        for node_id, description in descriptions.items():
            if node_id in client.graph:
                client.graph.nodes[node_id]["description"] = description
                updated += 1
        client.save()
    finally:
        client.close()

    import shutil

    shutil.rmtree(describe_dir, ignore_errors=True)
    return updated
