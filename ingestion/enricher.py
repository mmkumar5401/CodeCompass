"""Graph enrichment — an LLM agent swarm fills what static analysis can't.

Tree-sitter gives structure; this pass hands each entity's source to the
driving coding agent (staged batches it merges back with --apply) and
asks for two things per entity:

1. A one-line description (meaning, from actually reading the code).
2. Missing CALLS edges — callees visible in the source that the parser did
   not record (dynamic dispatch, reflection, string-based invocation,
   receivers it could not type).

`codecompass enrich <repo>` stages .codecompass/enrich/batch_XXXX.json +
INSTRUCTIONS.md. The driving agent dispatches one sub-agent per batch, each
writing batch_XXXX.result.json. `codecompass enrich <repo> --apply` merges
descriptions and every unambiguous missing call into the graph. Edges added
this way carry agent_inferred=True so they stay distinguishable from
parser-derived edges.
"""

from __future__ import annotations

import json
import os
from typing import Any

from graph.code_graph_client import get_client
from ingestion.source_context import extract_entity_context


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

DEFAULT_BATCH_SIZE = 15
ENRICH_SUBDIR = os.path.join(".codecompass", "enrich")

_INSTRUCTIONS_TEMPLATE = """\
# Graph enrichment — agent swarm task

{num_entities} entities across {num_batches} batch file(s) in this directory
need enrichment for the code knowledge graph.

## What to do

1. For each `batch_XXXX.json` file here, dispatch one sub-agent (in parallel).
   Give each sub-agent this task:

   > Read `{enrich_dir}/batch_XXXX.json`. It is a JSON list of entities, each
   > with `id`, `name`, `kind`, `file`, `line`, `signature`, `docstring`,
   > `snippet`, `known_callees`, and `known_callers`. For every entity:
   >
   > 1. Write ONE clear sentence describing what it does or its role.
   > 2. Read its `snippet` and list any calls the graph missed: functions or
   >    methods invoked in the source that are NOT in `known_callees`
   >    (dynamic dispatch, reflection, callbacks, string-based lookup). Give
   >    the callee's plain name as it would be defined in this repo.
   >
   > Write `{enrich_dir}/batch_XXXX.result.json`: a JSON object mapping each
   > entity `id` to {{"description": "...", "missing_calls": [{{"to": "name",
   > "line": <line number or null>}}]}}. Use an empty list when nothing is
   > missing. Do NOT invent calls you cannot see in the snippet. Output
   > nothing else — no markdown fences, no commentary, just the file.

2. Once every `batch_XXXX.result.json` file exists, run:

   ```
   codecompass enrich {repo_path} --apply
   ```

   This merges descriptions and resolvable call edges into the graph and
   cleans up this directory. Calls whose name matches more than one entity
   are skipped (ambiguous) and reported, not guessed.

## Batches

{batch_list}
"""


def _enrich_dir(repo_path: str) -> str:
    return os.path.join(os.path.abspath(repo_path), ENRICH_SUBDIR)


def _known_edges(client, node_id: str) -> dict[str, list[str]]:
    """Current callers/callees of an entity, as plain name lists."""
    callees, callers = [], []
    for _, succ, e in client.graph.out_edges(node_id, data=True):
        if e.get("type") == "CALLS":
            name = client.graph.nodes[succ].get("name")
            if name and name not in callees:
                callees.append(name)
    for pred, _, e in client.graph.in_edges(node_id, data=True):
        if e.get("type") == "CALLS":
            name = client.graph.nodes[pred].get("name")
            if name and name not in callers:
                callers.append(name)
    return {"known_callees": sorted(callees), "known_callers": sorted(callers)}


def prepare_enrich_batches(
    repo_path: str, batch_size: int = DEFAULT_BATCH_SIZE, force: bool = False
) -> dict[str, Any]:
    """Stage in-project entities into enrich batch files + an instructions doc.

    Returns {"num_entities", "num_batches", "enrich_dir", "instructions_path"}.
    Raises RuntimeError if unapplied result files from a previous run exist —
    pass force=True to discard and restage.
    """
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    enrich_dir = _enrich_dir(repo_path)

    if not force and os.path.isdir(enrich_dir):
        existing = [f for f in os.listdir(enrich_dir) if f.endswith(".result.json")]
        if existing:
            raise RuntimeError(
                f"{len(existing)} result file(s) already staged at {enrich_dir} "
                "from a previous enrich run. Run `codecompass enrich "
                f"{repo_path} --apply` to finish it first, or re-run with "
                "force=True to discard them and restage."
            )

    payloads = []
    client = get_client(repo_path)
    try:
        for node_id, attr in client.graph.nodes(data=True):
            if (attr.get("type") != "Entity" or attr.get("project") != project
                    or not attr.get("file")):
                continue
            payload = _entity_context(repo_path, node_id, attr)
            payload["line"] = attr.get("line")
            payload.update(_known_edges(client, node_id))
            payloads.append(payload)
    finally:
        client.close()

    result = {
        "num_entities": len(payloads),
        "num_batches": 0,
        "enrich_dir": enrich_dir,
        "instructions_path": None,
    }
    if not payloads:
        return result

    os.makedirs(enrich_dir, exist_ok=True)
    batches = [payloads[i : i + batch_size] for i in range(0, len(payloads), batch_size)]
    batch_names = []
    for idx, batch in enumerate(batches):
        batch_name = f"batch_{idx:04d}.json"
        with open(os.path.join(enrich_dir, batch_name), "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)
        batch_names.append(batch_name)

    instructions_path = os.path.join(enrich_dir, "INSTRUCTIONS.md")
    with open(instructions_path, "w", encoding="utf-8") as f:
        f.write(
            _INSTRUCTIONS_TEMPLATE.format(
                num_entities=len(payloads),
                num_batches=len(batches),
                enrich_dir=enrich_dir,
                repo_path=repo_path,
                batch_list="\n".join(f"- {name}" for name in batch_names),
            )
        )

    result["num_batches"] = len(batches)
    result["instructions_path"] = instructions_path
    return result


def _resolve_callee(client, project: str, name: str) -> str | None:
    """Node id of the single in-project entity called `name`, else None.

    Ambiguous names (multiple definitions) are never guessed — the parser's
    whole unresolved-receiver problem lives here, and a wrong edge is worse
    than a missing one.
    """
    matches = [
        nid for nid, a in client.graph.nodes(data=True)
        if a.get("type") == "Entity" and a.get("project") == project
        and a.get("file") and a.get("name") == name
    ]
    return matches[0] if len(matches) == 1 else None


def add_entity(repo_path: str, name: str, kind: str = "function",
               file: str = "", line: int | None = None,
               description: str = "", language: str = "") -> dict[str, str]:
    """Upsert one entity the agent found while reading code but the parser
    missed (or under-described). Populates the same fields a parser node has
    (language inferred from the file extension, kind as `type:language`,
    fallback description) and marks it agent_inferred. Returns created/updated."""
    from graph.code_graph_client import _EXT_TO_LANGUAGE

    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    if not language and file:
        language = _EXT_TO_LANGUAGE.get(os.path.splitext(file)[1].lower(), "")
    entity_type = kind.split(":", 1)[0]
    if ":" not in kind and language:
        kind = f"{entity_type}:{language}"
    fallback_desc = (f"{language} {entity_type} in {file}" if file
                     else f"{language} {entity_type}").strip()

    client = get_client(repo_path)
    try:
        existing = next(
            (nid for nid, a in client.graph.nodes(data=True)
             if a.get("type") == "Entity" and a.get("project") == project
             and a.get("name") == name and (not file or a.get("file") == file)),
            None,
        )
        status = "updated" if existing else "created"
        node_id = existing or f"{project}:{file}:{name}" if file else f"{project}:{name}"
        client.graph.add_node(node_id)
        node = client.graph.nodes[node_id]
        node.setdefault("type", "Entity")
        node.setdefault("name", name)
        node.setdefault("project", project)
        node["kind"] = kind
        node["entity_type"] = entity_type
        # Agent-given description wins; keep an existing one; else placeholder.
        node["description"] = description or node.get("description") or fallback_desc
        if language:
            node["language"] = language
        if file:
            node["file"] = file
        if line:
            node["line"] = line
        node["agent_inferred"] = True
        node["agent_created"] = True  # wholly agent-owned: resurrect on re-ingest
        client.save()
        return {"status": status, "id": node_id}
    finally:
        client.close()


def add_call(repo_path: str, caller: str, callee: str,
             line: int | None = None) -> dict[str, str]:
    """Record a CALLS edge the agent spotted in source but the parser missed.
    Both ends must resolve unambiguously — ambiguous names are skipped, never
    guessed. Idempotent: an existing CALLS edge is left alone."""
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    client = get_client(repo_path)
    try:
        from_id = _resolve_callee(client, project, caller)
        to_id = _resolve_callee(client, project, callee)
        if from_id is None:
            return {"status": "skipped", "reason": f"caller {caller!r} not found or ambiguous"}
        if to_id is None:
            return {"status": "skipped", "reason": f"callee {callee!r} not found or ambiguous"}
        already = any(
            e.get("type") == "CALLS"
            for e in client.graph.get_edge_data(from_id, to_id, default={}).values()
        )
        if already:
            return {"status": "exists", "from": from_id, "to": to_id}
        client.graph.add_edge(
            from_id, to_id,
            type="CALLS",
            source_file=client.graph.nodes[from_id].get("file", ""),
            line=line,
            resolved=False,
            agent_inferred=True,
        )
        client.save()
        return {"status": "added", "from": from_id, "to": to_id}
    finally:
        client.close()


def apply_enrich_results(repo_path: str) -> dict[str, int]:
    """Merge enrich result files into the graph and clean up.

    Returns {"descriptions", "edges_added", "calls_skipped"}.
    Raises FileNotFoundError if no staged enrich directory exists.
    """
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    enrich_dir = _enrich_dir(repo_path)
    if not os.path.isdir(enrich_dir):
        raise FileNotFoundError(
            f"No staged enrich batches found at {enrich_dir}. "
            "Run `codecompass enrich <repo_path>` first."
        )

    updates: dict[str, Any] = {}
    for name in sorted(f for f in os.listdir(enrich_dir) if f.endswith(".result.json")):
        with open(os.path.join(enrich_dir, name), encoding="utf-8") as f:
            try:
                updates.update(json.load(f))
            except json.JSONDecodeError:
                continue

    stats = {"descriptions": 0, "edges_added": 0, "calls_skipped": 0}
    client = get_client(repo_path)
    try:
        for node_id, update in updates.items():
            if node_id not in client.graph:
                continue
            if isinstance(update, str):  # lenient: description-only result
                update = {"description": update}
            description = (update.get("description") or "").strip()
            if description:
                node = client.graph.nodes[node_id]
                node["description"] = description
                node["agent_inferred"] = True  # preserve across re-ingest
                stats["descriptions"] += 1
            for call in update.get("missing_calls") or []:
                to_name = (call.get("to") or "").strip()
                if not to_name:
                    continue
                to_id = _resolve_callee(client, project, to_name)
                if to_id is None:
                    stats["calls_skipped"] += 1
                    continue
                already = any(
                    e.get("type") == "CALLS"
                    for e in client.graph.get_edge_data(node_id, to_id, default={}).values()
                )
                if already:
                    continue
                client.graph.add_edge(
                    node_id, to_id,
                    type="CALLS",
                    source_file=client.graph.nodes[node_id].get("file", ""),
                    line=call.get("line"),
                    resolved=False,
                    agent_inferred=True,
                )
                stats["edges_added"] += 1
        client.save()
    finally:
        client.close()

    import shutil

    shutil.rmtree(enrich_dir, ignore_errors=True)
    return stats
