"""Agent-authored graph writes — the only way facts get added by hand.

Tree-sitter gives structure; everything it cannot see (dynamic dispatch,
reflection, string-based invocation, runtime-registered base classes) and
everything it cannot know (what an entity is actually FOR) comes from an agent
that read the code and wrote it back:

  add_entity(name, kind, file, line, description)  -> node, plus its description
  add_call(caller, callee, line, relation=...)     -> CALLS / IMPORTS / INHERITS
  delete_entity(name, file)                        -> remove agent knowledge
  delete_call(caller, callee, relation=...)        -> remove an agent edge

Descriptions are stored as a `description` attribute on the node itself. The
ingest rebuild carries node attributes from the old graph onto the new one
(fresh parser values win, and the parser never writes descriptions), so a
description survives exactly as long as its node does. Everything written here
is flagged agent_inferred (plus agent_created on a node the parser has never
produced), because an entity or edge absent from a fresh parse is otherwise
indistinguishable from one deleted from source: the flags are what let the
ingest join re-add YOUR work without resurrecting code you removed. Describing
an entity the parser does produce flags nothing — a deleted symbol still stays
deleted, description and all. Ambiguous names are skipped rather than guessed:
a wrong edge is worse than a missing one.
"""

from __future__ import annotations

import os

from graph.code_graph_client import get_client


def _candidate_list(client, project: str, name: str) -> list[dict]:
    """Every in-project entity called `name`, as {id, file} — what an ambiguous
    add/delete hands back so the caller can retry with file or id."""
    return [{"id": nid, "file": a.get("file", "")}
            for nid, a in client.graph.nodes(data=True)
            if a.get("type") == "Entity" and a.get("project") == project
            and a.get("file") and a.get("name") == name]


def _resolve_one(client, project: str, name: str, file: str = "",
                 allow_external: bool = False) -> tuple[str | None, list[dict]]:
    """(node id, candidates) for one endpoint. Exactly one match wins; zero or
    several return None plus the candidate list for an informed retry.
    allow_external also admits the file-less nodes the parser emits for
    stdlib/third-party modules (an IMPORTS target may be one of those)."""
    matches = [
        nid for nid, a in client.graph.nodes(data=True)
        if a.get("type") == "Entity" and a.get("project") == project
        and (a.get("file") or allow_external) and a.get("name") == name
        and (not file or a.get("file") == file)
    ]
    if len(matches) == 1:
        return matches[0], []
    return None, _candidate_list(client, project, name)


def add_entity(repo_path: str, name: str, kind: str = "function",
               file: str = "", line: int | None = None,
               description: str = "", language: str = "") -> dict[str, str]:
    """Upsert one entity the agent found while reading code but the parser
    missed (or left undescribed). Populates the same fields a parser node has
    (language inferred from the file extension, kind as `type:language`); the
    description is set as a node attribute. A node the parser has never
    produced is marked agent_created so it survives re-ingest — as long as its
    file still exists. Returns created/updated."""
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
        existing_matches = [
            nid for nid, a in client.graph.nodes(data=True)
            if a.get("type") == "Entity" and a.get("project") == project
            and a.get("name") == name and (not file or a.get("file") == file)
        ]
        if len(existing_matches) > 1:
            return {"status": "ambiguous",
                    "reason": f"{len(existing_matches)} entities named {name!r} — pass file to target one",
                    "candidates": _candidate_list(client, project, name)}
        existing = existing_matches[0] if existing_matches else None
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


# Relations an agent may NOT write: the structural hierarchy is parser-owned
# and a guessed one corrupts it. Everything else is free-form — the agent
# passes whatever relation the code actually shows (CALLS, IMPORTS, INHERITS,
# OVERRIDES, DISPATCHES, LISTENS_TO, …), normalized to UPPER_SNAKE.
PARSER_OWNED_RELATIONS = ("CONTAINS", "DEFINED_IN")


def _normalize_relation(relation: str) -> str | None:
    """Free-form relation → canonical form, or None when it's parser-owned."""
    rel = (relation or "").strip().upper().replace(" ", "_").replace("-", "_")
    if not rel or rel in PARSER_OWNED_RELATIONS:
        return None
    return rel


def add_call(repo_path: str, caller: str, callee: str,
             line: int | None = None, relation: str = "CALLS",
             caller_file: str = "", callee_file: str = "") -> dict[str, object]:
    """Record an edge the agent spotted in source but the parser missed.
    relation is free-form (CALLS by default; IMPORTS, INHERITS, OVERRIDES,
    DISPATCHES — whatever the code shows); only the parser-owned structural
    relations CONTAINS/DEFINED_IN are refused. When a name is shared across
    files, pass caller_file / callee_file to target the right one — an
    ambiguous name returns the candidates for a precise retry.
    Idempotent: an existing edge of the same type is left alone."""
    relation = _normalize_relation(relation)
    if relation is None:
        return {"status": "skipped",
                "reason": f"relation empty or parser-owned ({', '.join(PARSER_OWNED_RELATIONS)})"}
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    client = get_client(repo_path)
    try:
        imports = relation == "IMPORTS"
        from_id, from_cands = _resolve_one(client, project, caller, caller_file)
        # An import target may be a stdlib/third-party module, which lives in
        # the graph as a file-less node — or not at all, the first time anyone
        # records it.
        to_id, to_cands = _resolve_one(client, project, callee, callee_file,
                                       allow_external=imports)
        if from_id is None:
            return ({"status": "ambiguous", "side": "caller",
                     "candidates": from_cands} if from_cands
                    else {"status": "skipped", "reason": f"caller {caller!r} not found"})
        # Only when nothing of that name exists — an ambiguous name still returns candidates.
        if (to_id is None and not to_cands and imports):
            to_id = f"{project}:{callee}"
            language = client.graph.nodes[from_id].get("language", "")
            client.graph.add_node(
                to_id, type="Entity", name=callee, project=project,
                entity_type="module", kind=f"module:{language}" if language else "module",
                language=language, agent_inferred=True, agent_created=True,
            )
        if to_id is None:
            return ({"status": "ambiguous", "side": "callee",
                     "candidates": to_cands} if to_cands
                    else {"status": "skipped", "reason": f"callee {callee!r} not found"})
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


def delete_entity(repo_path: str, name: str = "", file: str = "",
                  id: str = "") -> dict[str, object]:
    """Remove agent-written knowledge about an entity.

    Target it exactly ONE way: `id` (a node id from grep/impact output) or
    `name` (+ `file` when the name is shared). A node the agent created
    (agent_created) is removed outright, edges and description with it —
    nothing will resurrect it, since the parser never produced it. A
    parser-produced node is parser-owned: only the agent's additions
    (description, agent_inferred flags and edges) are stripped, because the
    node itself would be re-parsed on the next ingest anyway. An ambiguous
    name returns the candidates — retry with file or id.
    """
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    client = get_client(repo_path)
    try:
        if id:
            if id not in client.graph:
                return {"status": "not_found", "id": id}
            matches = [id]
        else:
            matches = [
                nid for nid, a in client.graph.nodes(data=True)
                if a.get("type") == "Entity" and a.get("project") == project
                and a.get("name") == name and (not file or a.get("file") == file)
            ]
        if not matches:
            return {"status": "not_found", "name": name or id}
        if len(matches) > 1:
            return {"status": "ambiguous",
                    "reason": f"{len(matches)} entities named {name!r} — retry with file or id",
                    "candidates": _candidate_list(client, project, name)}
        node_id = matches[0]
        node = client.graph.nodes[node_id]
        if node.get("agent_created"):
            client.graph.remove_node(node_id)  # edges die with it
            client.save()
            return {"status": "deleted", "id": node_id}
        removed = [k for k in ("description", "agent_inferred") if node.pop(k, None) is not None]
        # agent_inferred edges touching a parser node are agent-owned too
        edges_removed = 0
        for u, v, k, e in list(client.graph.edges(keys=True, data=True)):
            if node_id in (u, v) and e.get("agent_inferred"):
                client.graph.remove_edge(u, v, k)
                edges_removed += 1
        client.save()
        return {"status": "stripped", "id": node_id,
                "removed": removed + [f"{edges_removed} agent edge(s)"],
                "reason": "parser-owned node kept — the parser would restore it on ingest anyway"}
    finally:
        client.close()


def delete_call(repo_path: str, caller: str, callee: str,
                relation: str = "CALLS", caller_file: str = "",
                callee_file: str = "") -> dict[str, object]:
    """Remove an agent-recorded edge (add_call's undo).

    Only agent_inferred edges are touched: parser edges are parser-owned, and
    deleting one would be pointless — the next ingest re-parses it. Pass
    caller_file / callee_file when a name is shared; an ambiguous name returns
    the candidates for a precise retry. Returns removed / not_found /
    ambiguous / skipped.
    """
    relation = _normalize_relation(relation)
    if relation is None:
        return {"status": "skipped",
                "reason": f"relation empty or parser-owned ({', '.join(PARSER_OWNED_RELATIONS)})"}
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    client = get_client(repo_path)
    try:
        from_id, from_cands = _resolve_one(client, project, caller, caller_file)
        to_id, to_cands = _resolve_one(client, project, callee, callee_file,
                                       allow_external=True)
        if from_id is None:
            return ({"status": "ambiguous", "side": "caller",
                     "candidates": from_cands} if from_cands
                    else {"status": "skipped", "reason": f"caller {caller!r} not found"})
        if to_id is None:
            return ({"status": "ambiguous", "side": "callee",
                     "candidates": to_cands} if to_cands
                    else {"status": "skipped", "reason": f"callee {callee!r} not found"})
        keys = [k for k, e in client.graph.get_edge_data(from_id, to_id, default={}).items()
                if e.get("type") == relation]
        if not keys:
            return {"status": "not_found", "from": from_id, "to": to_id,
                    "relation": relation}
        if not any(client.graph.edges[from_id, to_id, k].get("agent_inferred") for k in keys):
            return {"status": "skipped",
                    "reason": "edge is parser-owned — it would be re-parsed on ingest anyway"}
        for k in keys:
            if client.graph.edges[from_id, to_id, k].get("agent_inferred"):
                client.graph.remove_edge(from_id, to_id, k)
        client.save()
        return {"status": "removed", "from": from_id, "to": to_id,
                "relation": relation}
    finally:
        client.close()


def modify_relation(repo_path: str, caller: str, callee: str,
                    to_relation: str, from_relation: str = "",
                    caller_file: str = "", callee_file: str = "") -> dict[str, object]:
    """Change the relation type on an existing edge — including a parser edge
    the parser got wrong (it says CALLS, the code actually INHERITS).

    The retyped edge is marked agent_relation=True: on the next ingest join,
    the agent's relation WINS for that node pair — the parser's freshly parsed
    edge of the old type is dropped, and the agent's relation is restored if
    the edge vanished. from_relation narrows which edge to retype when several
    types link the pair; omit it when only one does. Pass caller_file /
    callee_file for shared names. Returns modified / not_found / ambiguous /
    skipped.
    """
    to_relation = _normalize_relation(to_relation)
    if to_relation is None:
        return {"status": "skipped",
                "reason": f"to_relation empty or parser-owned ({', '.join(PARSER_OWNED_RELATIONS)})"}
    from_relation = (_normalize_relation(from_relation) if from_relation else "")
    repo_path = os.path.abspath(repo_path)
    project = os.path.basename(repo_path)
    client = get_client(repo_path)
    try:
        from_id, from_cands = _resolve_one(client, project, caller, caller_file)
        to_id, to_cands = _resolve_one(client, project, callee, callee_file,
                                       allow_external=True)
        if from_id is None:
            return ({"status": "ambiguous", "side": "caller",
                     "candidates": from_cands} if from_cands
                    else {"status": "skipped", "reason": f"caller {caller!r} not found"})
        if to_id is None:
            return ({"status": "ambiguous", "side": "callee",
                     "candidates": to_cands} if to_cands
                    else {"status": "skipped", "reason": f"callee {callee!r} not found"})

        edges = client.graph.get_edge_data(from_id, to_id, default={})
        types = sorted({e.get("type") for e in edges.values()})
        if from_relation:
            if from_relation not in types:
                return {"status": "not_found", "from": from_id, "to": to_id,
                        "relation": from_relation}
            target_types = [from_relation]
        elif len(types) == 1:
            target_types = types
        elif not types:
            return {"status": "not_found", "from": from_id, "to": to_id}
        else:
            return {"status": "ambiguous",
                    "reason": "several relations link this pair — pass from_relation",
                    "candidates": [{"relation": t} for t in types]}

        changed = 0
        for k, e in list(edges.items()):
            if e.get("type") not in target_types:
                continue
            attrs = dict(e)
            attrs["type"] = to_relation
            attrs["agent_inferred"] = True
            attrs["agent_relation"] = True  # join: this relation wins over the parser's
            client.graph.remove_edge(from_id, to_id, k)
            client.graph.add_edge(from_id, to_id, **attrs)
            changed += 1
        client.save()
        return {"status": "modified", "from": from_id, "to": to_id,
                "from_relation": target_types[0], "to_relation": to_relation,
                "count": changed}
    finally:
        client.close()
