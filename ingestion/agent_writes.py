"""Agent-authored graph writes — the only way facts get added by hand.

Tree-sitter gives structure; everything it cannot see (dynamic dispatch,
reflection, string-based invocation, runtime-registered base classes) and
everything it cannot know (what an entity is actually FOR) comes from an agent
that read the code and wrote it back:

  add_entity(name, kind, file, line, description)  -> node, plus its description
  add_call(caller, callee, line, relation=...)     -> CALLS / IMPORTS / INHERITS

Descriptions are stored in .codecompass/description.jsonl keyed by node id, not
on the nodes themselves, so they survive the wholesale graph rebuild each
ingest performs. Everything written here is flagged agent_inferred (plus
agent_created on a node the parser has never produced), because an entity or
edge absent from a fresh parse is otherwise indistinguishable from one deleted
from source: the flags are what let the ingest join re-add YOUR work without
resurrecting code you removed. Describing an entity the parser does produce
flags nothing — the description lives in the sidecar and the node stands on its
own. Ambiguous names are skipped rather than guessed: a wrong edge is worse
than a missing one.
"""

from __future__ import annotations

import os

from graph.code_graph_client import get_client


def _resolve_callee(client, project: str, name: str,
                    allow_external: bool = False) -> str | None:
    """Node id of the single entity called `name`, else None.

    In-project entities (those with a file) only, unless allow_external — the
    parser also emits file-less nodes for imported stdlib/third-party modules,
    and an IMPORTS target may legitimately be one of those.

    Ambiguous names (multiple definitions) are never guessed — the parser's
    whole unresolved-receiver problem lives here, and a wrong edge is worse
    than a missing one.
    """
    matches = _match_ids(client, project, name, allow_external)
    return matches[0] if len(matches) == 1 else None


def _match_ids(client, project: str, name: str, allow_external: bool = False) -> list:
    return [
        nid for nid, a in client.graph.nodes(data=True)
        if a.get("type") == "Entity" and a.get("project") == project
        and (a.get("file") or allow_external) and a.get("name") == name
    ]


def add_entity(repo_path: str, name: str, kind: str = "function",
               file: str = "", line: int | None = None,
               description: str = "", language: str = "") -> dict[str, str]:
    """Upsert one entity the agent found while reading code but the parser
    missed (or left undescribed). Populates the same fields a parser node has
    (language inferred from the file extension, kind as `type:language`); the
    description goes to the sidecar, keyed by node id. A node the parser has
    never produced is marked agent_created so it survives re-ingest — as long as
    its file still exists. Returns created/updated."""
    from graph.code_graph_client import _EXT_TO_LANGUAGE

    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    if not language and file:
        language = _EXT_TO_LANGUAGE.get(os.path.splitext(file)[1].lower(), "")
    entity_type = kind.split(":", 1)[0]
    if ":" not in kind and language:
        kind = f"{entity_type}:{language}"

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
        if language:
            node["language"] = language
        if file:
            node["file"] = file
        if line:
            node["line"] = line
        if not existing:
            # The parser has never produced this node, so the ingest join has
            # nothing to match it against — these two flags are what carry it
            # across the rebuild. Describing a node the parser DOES produce sets
            # neither, so a deleted symbol stays deleted.
            node["agent_inferred"] = True
            node["agent_created"] = True
        if description:
            client.set_description(node_id, description)
        client.save()
        return {"status": status, "id": node_id}
    finally:
        client.close()


# Edge types an agent may record. CONTAINS/DEFINED_IN are structural — the
# parser owns the hierarchy and a guessed one corrupts it.
AGENT_RELATIONS = ("CALLS", "IMPORTS", "INHERITS")


def add_call(repo_path: str, caller: str, callee: str,
             line: int | None = None, relation: str = "CALLS") -> dict[str, str]:
    """Record an edge the agent spotted in source but the parser missed.
    relation is one of AGENT_RELATIONS (CALLS by default). Both ends must
    resolve unambiguously — ambiguous names are skipped, never guessed.
    Idempotent: an existing edge of the same type is left alone."""
    relation = relation.upper()
    if relation not in AGENT_RELATIONS:
        return {"status": "skipped",
                "reason": f"relation {relation!r} not one of {', '.join(AGENT_RELATIONS)}"}
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    client = get_client(repo_path)
    try:
        imports = relation == "IMPORTS"
        from_id = _resolve_callee(client, project, caller)
        # An import target may be a stdlib/third-party module, which lives in
        # the graph as a file-less node — or not at all, the first time anyone
        # records it.
        to_id = _resolve_callee(client, project, callee, allow_external=imports)
        if from_id is None:
            return {"status": "skipped", "reason": f"caller {caller!r} not found or ambiguous"}
        # Only when nothing of that name exists — an ambiguous name still skips.
        if (to_id is None and imports
                and not _match_ids(client, project, callee, allow_external=True)):
            to_id = f"{project}:{callee}"
            language = client.graph.nodes[from_id].get("language", "")
            client.graph.add_node(
                to_id, type="Entity", name=callee, project=project,
                entity_type="module", kind=f"module:{language}" if language else "module",
                language=language, agent_inferred=True, agent_created=True,
            )
        if to_id is None:
            return {"status": "skipped", "reason": f"callee {callee!r} not found or ambiguous"}
        already = any(
            e.get("type") == relation
            for e in client.graph.get_edge_data(from_id, to_id, default={}).values()
        )
        if already:
            return {"status": "exists", "from": from_id, "to": to_id}
        client.graph.add_edge(
            from_id, to_id,
            type=relation,
            source_file=client.graph.nodes[from_id].get("file", ""),
            line=line,
            resolved=False,
            agent_inferred=True,
        )
        client.save()
        return {"status": "added", "from": from_id, "to": to_id}
    finally:
        client.close()
