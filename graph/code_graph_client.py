# Source files are authoritative; this graph is a stale-tolerant index that degrades gracefully.
"""Local graph client for code knowledge graphs.
Replaces Neo4j with NetworkX and JSON persistence.
"""

from __future__ import annotations

import json
import os
import re
import networkx as nx
from datetime import datetime, timezone
from typing import Optional, Any

from models.code_types import CodeTriple, FileNode, FolderNode

# Relationship types emitted by code_parser.
_EXT_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".php": "php",
}

_ALLOWED_REL_TYPES = frozenset({
    "CALLS", "IMPORTS", "INHERITS", "DEFINED_IN",
    "HAS_CLASS", "POSTS_TO", "INCLUDES", "STYLES", "USED_BY",
    "USES_VAR", "REFERENCES",
})

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entity_id(project: str, name: str, file: str | None, owner: str | None = None) -> str:
    """Node id for an entity — file- and class-qualified so same-named entities
    stay distinct across files AND across classes in the same file. Case is
    preserved so `Session` (class) and `session` (function) don't collide.
    External/module targets with no file are name-only.
    """
    if file:
        local = f"{owner}.{name}" if owner else name
        return f"{project}:{file}:{local}"
    return f"{project}:{name}"


_ENTRY_POINT_PREFIXES = ("run_", "main", "handle_", "cmd_", "test_", "setup_", "teardown_")
_ENTRY_POINT_NAMES = {"main", "__main__", "handler", "lambda_handler", "application", "app"}


def _strip_code_ext(path: str) -> str:
    for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".php"):
        if path.endswith(ext):
            return path[: -len(ext)]
    return path


def _import_resolves_to(import_str: str, from_file: str, target_file: str) -> bool:
    """True if `import_str` written in `from_file` refers to `target_file`.

    Resolves relative CommonJS/ESM specifiers (`./response`, `../lib/response`,
    with an implicit `/index`) and dotted module names (`lib.response`) against
    the target's extension-stripped path. Package imports (`router`, `express`)
    never match a project file and return False.
    """
    if not import_str or not target_file:
        return False
    target_base = _strip_code_ext(target_file).replace("\\", "/")

    if import_str.startswith("."):
        from_dir = os.path.dirname(from_file)
        resolved = os.path.normpath(os.path.join(from_dir, import_str)).replace("\\", "/")
        # Direct match, or the specifier points at a directory whose index file
        # is the target (`./lib` → `lib/index.js`).
        return resolved == target_base or target_base == f"{resolved}/index"

    if "." in import_str and "/" not in import_str:
        # Dotted module name, e.g. "lib.response" → "lib/response".
        dotted = import_str.replace(".", "/")
        return dotted == target_base

    return False


def _receiver_matches(want: str, actual: str | None, actual_type: str | None = None) -> bool:
    """True if a call's receiver satisfies a qualified query `want`.

    Resolution order:
      1. Inferred receiver type ("Router.handle" matches calls typed Router).
         This is the strongest signal and is name-independent.
      2. Self-references (`this`/`self`) — assumed to hit the queried object.
      3. Receiver name — exact ("app") or trailing chain segment
         ("this.router" endswith ".router").

    Once a receiver's *type* is known and differs from `want`, a coincidental
    name match is rejected — a `new Router()` call never satisfies "app.handle".
    """
    if actual_type is not None and actual_type == want:
        return True
    if actual in ("this", "self"):
        return True
    if actual_type is not None and actual_type != want:
        return False
    if actual is None:
        return False
    if actual == want:
        return True
    return actual.endswith("." + want)


def _looks_like_entry_point(name: str, entity_type: str) -> bool:
    """Heuristic: names invoked by a runtime/dispatcher, not by static calls.

    CLI subcommands, request handlers, and test functions have no in-repo caller
    yet are clearly live. Modules are containers, never "dead" in the call sense.
    """
    if entity_type == "module":
        return True
    # Dunder methods (`__call__`, `__get__`, `__enter__`, …) are invoked by the
    # language runtime / protocols, never by an explicit in-repo call site.
    if name.startswith("__") and name.endswith("__") and len(name) > 4:
        return True
    lowered = name.lower()
    if lowered in _ENTRY_POINT_NAMES:
        return True
    return lowered.startswith(_ENTRY_POINT_PREFIXES)


class LocalGraphClient:
    """Manages code-graph persistence using NetworkX and a local JSON file."""

    def __init__(self, storage_path: str) -> None:
        self.storage_path = storage_path
        self.graph = nx.MultiDiGraph()
        self.load()

    def load(self) -> None:
        """Load graph from JSON file."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    self.graph = nx.node_link_graph(data, edges="links")
            except (json.JSONDecodeError, Exception) as e:
                print(f"Warning: Could not load graph from {self.storage_path} ({e}). Starting fresh.")
                self.graph = nx.MultiDiGraph()

    def save(self) -> None:
        """Save graph to JSON file."""
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        data = nx.node_link_data(self.graph, edges="links")
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    # Structural nodes (hierarchy skeleton)
    # ------------------------------------------------------------------

    def merge_project_node(self, node_id: str, name: str, path: str) -> None:
        self.graph.add_node(
            node_id, 
            type="Project", 
            name=name, 
            path=path, 
            last_ingested=_now()
        )

    def merge_folder_node(self, node_id: str, folder: FolderNode, project: str) -> None:
        self.graph.add_node(
            node_id, 
            type="Folder", 
            name=folder.name, 
            path=folder.path, 
            depth=folder.depth, 
            project=project
        )

    def merge_file_node(self, node_id: str, file: FileNode, project: str) -> None:
        self.graph.add_node(
            node_id, 
            type="File", 
            name=file.name, 
            path=file.path, 
            extension=file.extension, 
            depth=file.depth, 
            project=project, 
            updated_at=_now()
        )

    def merge_contains_edge(self, parent_id: str, child_id: str) -> None:
        self.graph.add_edge(parent_id, child_id, type="CONTAINS")

    # ------------------------------------------------------------------
    # Entity nodes and semantic edges (from code triples)
    # ------------------------------------------------------------------

    def write_code_triple(self, triple: CodeTriple, file_node_id: str, project: str,
                          from_id: str | None = None, to_id: str | None = None) -> None:
        # from_id/to_id are the resolved (file-qualified) node ids from the batch
        # writer; fall back to name-only for any direct/legacy caller.
        if from_id is None:
            from_id = f"{project}:{triple.from_entity}"
        if to_id is None:
            to_id = f"{project}:{triple.to_entity}"
        rel_type = triple.relation_type if triple.relation_type in _ALLOWED_REL_TYPES else "RELATION"

        ext = os.path.splitext(triple.source_file)[1].lower()
        language = _EXT_TO_LANGUAGE.get(ext, "unknown")

        # Upsert from entity (always has a known source file)
        self.graph.add_node(from_id)
        self.graph.nodes[from_id].update({
            "type": "Entity",
            "name": triple.from_entity,
            "entity_type": triple.from_type,
            "language": language,
            "kind": f"{triple.from_type}:{language}",
            "description": f"{language} {triple.from_type} in {triple.source_file}",
            "project": project,
            "file": triple.source_file,
        })
        # A symbol is public if any of its definitions is exported. Never let a
        # later non-exported definition clear a flag an earlier one set.
        if getattr(triple, "is_exported", False):
            self.graph.nodes[from_id]["is_exported"] = True
        if getattr(triple, "owner_class", None):
            self.graph.nodes[from_id]["owner"] = triple.owner_class

        # Upsert to entity — only set language/kind/description if not already known
        self.graph.add_node(to_id)
        existing = self.graph.nodes[to_id]
        existing.setdefault("type", "Entity")
        existing.setdefault("name", triple.to_entity)
        existing.setdefault("entity_type", triple.to_type)
        existing.setdefault("project", project)
        if not existing.get("language"):
            existing["language"] = language
            existing["kind"] = f"{triple.to_type}:{language}"
            existing["description"] = f"{language} {triple.to_type}"

        self.graph.add_edge(
            from_id,
            to_id,
            type=rel_type,
            source_file=triple.source_file,
            line=triple.line_number,
            receiver=getattr(triple, "call_receiver", None),
            receiver_type=getattr(triple, "call_receiver_type", None),
            created_at=_now()
        )

        self.graph.add_edge(file_node_id, from_id, type="CONTAINS")

    def _resolve_to_id(self, triple: CodeTriple, project: str,
                       defs_by_name: dict, class_file: dict) -> str:
        """Resolve a triple's callee/target to a specific definition node when we
        can, else a name-only bucket. Uses the captured receiver type to pick the
        right same-named method (self.send() in a Session method -> the send
        defined alongside class Session)."""
        name = triple.to_entity
        if triple.relation_type == "DEFINED_IN":
            return f"{project}:{name}"  # module container — name-only
        cands = defs_by_name.get(name)  # list of (node_id, file, owner)
        if cands:
            rt = getattr(triple, "call_receiver_type", None)
            if rt:
                # strongest: a definition owned by exactly the receiver's class
                for nid, f, owner in cands:
                    if owner == rt:
                        return nid
                # next: any definition in the receiver class's file
                cf = class_file.get(rt)
                if cf:
                    for nid, f, owner in cands:
                        if f == cf:
                            return nid
            if len(cands) == 1:
                return cands[0][0]
        # ambiguous or external → name-only bucket (edge not lost)
        return f"{project}:{name}"

    def write_code_triples_batch(
        self,
        triples: list[CodeTriple],
        file_id_map: dict[str, str],
        project: str
    ) -> int:
        # Pass 1: index every definition so calls can resolve to a specific one.
        defs_by_name: dict[str, list] = {}   # name -> [(node_id, file, owner)]
        class_file: dict[str, str] = {}
        for t in triples:
            if t.relation_type == "DEFINED_IN":
                owner = getattr(t, "owner_class", None)
                nid = _entity_id(project, t.from_entity, t.source_file, owner)
                defs_by_name.setdefault(t.from_entity, []).append((nid, t.source_file, owner))
                if t.from_type == "class":
                    class_file.setdefault(t.from_entity, t.source_file)

        # Pass 2: write nodes/edges with resolved, file+class-qualified ids.
        for triple in triples:
            file_id = file_id_map.get(triple.source_file, "")
            from_id = _entity_id(project, triple.from_entity, triple.source_file,
                                 getattr(triple, "owner_class", None))
            to_id = self._resolve_to_id(triple, project, defs_by_name, class_file)
            self.write_code_triple(triple, file_id, project, from_id=from_id, to_id=to_id)

        self.save()
        return len(triples)

    def get_file_nodes(self, project: str) -> list[dict]:
        """Return {id, path} for every File node in a project."""
        return [
            {"id": n, "path": attr.get("path")}
            for n, attr in self.graph.nodes(data=True)
            if attr.get("type") == "File" and attr.get("project") == project
        ]

    def delete_file_entities(self, file_path: str) -> None:
        """Remove all Entity nodes sourced from file_path before re-ingesting."""
        to_remove = [
            n for n, attr in self.graph.nodes(data=True)
            if attr.get("type") == "Entity" and attr.get("file") == file_path
        ]
        for node in to_remove:
            self.graph.remove_node(node)

    def delete_file_triples(self, file_path: str, project: str) -> None:
        """Remove Entity nodes sourced from file_path; leave the File node intact."""
        self.delete_file_entities(file_path)

    def delete_file(self, file_path: str, project: str) -> None:
        """Remove the File node and all Entity nodes sourced from file_path."""
        self.delete_file_entities(file_path)
        to_remove = [
            n for n, attr in self.graph.nodes(data=True)
            if attr.get("type") == "File" and attr.get("path") == file_path
        ]
        for node in to_remove:
            self.graph.remove_node(node)

    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    def close(self) -> None:
        self.save()

    # ------------------------------------------------------------------
    # Traversal queries used by code_query_cli
    # ------------------------------------------------------------------

    def _resolve_query_nodes(self, entity_name: str, project: str) -> list[str]:
        """Resolve a bare or receiver-qualified name to the node id(s) it refers
        to. `Session.send` → the `send` node in the file where class `Session` is
        defined; `send` → every `send` node. Includes the name-only bucket id
        when present (unresolved/ambiguous calls land there)."""
        qualifier = None
        name = entity_name
        if "." in entity_name:
            qualifier, name = entity_name.rsplit(".", 1)
        name_l = name.lower()

        matches = [
            n for n, a in self.graph.nodes(data=True)
            if a.get("type") == "Entity" and (a.get("name") or "").lower() == name_l
        ]
        # name-only bucket (unresolved calls land here) is matched by its name attr,
        # but sort it last so flow/trace pick a real definition as the start.
        matches.sort(key=lambda n: self.graph.nodes[n].get("file") is None)

        if qualifier and matches:
            # strongest: nodes whose owner class IS the qualifier (Command.invoke)
            owned = [n for n in matches
                     if (self.graph.nodes[n].get("owner") or "").lower() == qualifier.lower()]
            if owned:
                return owned
            # next: nodes in the file where class <qualifier> is defined
            cls_files = {
                a.get("file") for n, a in self.graph.nodes(data=True)
                if a.get("type") == "Entity" and a.get("entity_type") == "class"
                and (a.get("name") or "").lower() == qualifier.lower() and a.get("file")
            }
            pref = [n for n in matches if self.graph.nodes[n].get("file") in cls_files]
            if pref:
                return pref
        return matches

    def find_callers(self, entity_name: str, project: str, max_hops: int = 3) -> list[dict]:
        """Return everything that calls/uses/references entity_name (reverse traversal).

        `entity_name` may be a bare name ("handle") or receiver-qualified
        ("app.handle" / "Router.handle"). Node ids are file-qualified, so distinct
        same-named methods are distinct nodes; a qualified query resolves to the
        one defined alongside the named class. The receiver filter still applies
        for calls that landed in a shared name-only bucket (genuinely ambiguous).
        Every returned row carries the call's `receiver`/`receiver_type` and the
        real call-site file+line.
        """
        want_receiver = None
        if "." in entity_name:
            want_receiver, _ = entity_name.rsplit(".", 1)

        targets = self._resolve_query_nodes(entity_name, project)
        if not targets:
            return []
        target_set = set(targets)

        results = []
        visited = set(targets)
        queue = [(t, 0) for t in targets]

        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_hops:
                continue

            for pred in self.graph.predecessors(current_id):
                edges = self.graph.get_edge_data(pred, current_id)
                relevant_edges = [
                    edge for edge in edges.values()
                    if edge.get("type") in {"CALLS", "USES_VAR", "REFERENCES"}
                ]
                if not relevant_edges or pred in visited:
                    continue

                # Only apply receiver filtering to the direct (depth-0) edge into
                # the queried symbol; deeper hops are transitive callers.
                if want_receiver is not None and current_id in target_set:
                    if not any(
                        _receiver_matches(want_receiver, edge.get("receiver"),
                                          edge.get("receiver_type"))
                        for edge in relevant_edges
                    ):
                        continue

                node = self.graph.nodes[pred]
                if node.get("type") == "Entity":
                    receiver = next(
                        (e.get("receiver") for e in relevant_edges if e.get("receiver")),
                        None,
                    )
                    receiver_type = next(
                        (e.get("receiver_type") for e in relevant_edges if e.get("receiver_type")),
                        None,
                    )
                    # The caller NODE is keyed by name only, so when two functions
                    # share a name its "file" is last-writer-wins (a merge). The
                    # CALLS edge, however, records where THIS call actually is —
                    # use it so each caller row points at the real call site with a
                    # line number, not the merged node's file.
                    call_edge = next(
                        (e for e in relevant_edges if e.get("source_file")), relevant_edges[0]
                    )
                    results.append({
                        "caller_name": node.get("name"),
                        "caller_type": node.get("entity_type"),
                        "caller_file": call_edge.get("source_file") or node.get("file"),
                        "line": call_edge.get("line"),
                        "receiver": receiver,
                        "receiver_type": receiver_type,
                        "resolved": True,
                        "depth": depth + 1
                    })
                    visited.add(pred)
                    queue.append((pred, depth + 1))

        # Qualified query (Type.method): if we found NO precise caller, fall back
        # to the name-only bucket — calls whose receiver couldn't be statically
        # typed (e.g. `adapter = self.get_adapter(url); adapter.send()`). They MAY
        # hit this method, so we surface them flagged resolved=False rather than
        # return nothing. We skip this when there's already a precise answer,
        # because the bucket for a common name (`invoke`) is mostly calls to OTHER
        # same-named methods and would flood a query that already resolved.
        if want_receiver is not None and not results:
            method = entity_name.rsplit(".", 1)[1]
            bucket = f"{project}:{method}"
            if bucket in self.graph and bucket not in target_set:
                for pred in self.graph.predecessors(bucket):
                    if pred in visited:
                        continue
                    rel = [e for e in self.graph.get_edge_data(pred, bucket).values()
                           if e.get("type") in {"CALLS", "USES_VAR", "REFERENCES"}]
                    node = self.graph.nodes[pred]
                    if not rel or node.get("type") != "Entity":
                        continue
                    ce = next((e for e in rel if e.get("source_file")), rel[0])
                    results.append({
                        "caller_name": node.get("name"),
                        "caller_type": node.get("entity_type"),
                        "caller_file": ce.get("source_file") or node.get("file"),
                        "line": ce.get("line"),
                        "receiver": next((e.get("receiver") for e in rel if e.get("receiver")), None),
                        "receiver_type": None,
                        "resolved": False,
                        "depth": 1,
                    })
                    visited.add(pred)

        return sorted(results, key=lambda x: (not x.get("resolved", True), x["depth"]))

    def grep_graph(self, pattern: str, project: str, field: str = "all",
                   ignore_case: bool = True, limit: int = 100) -> dict:
        """Regex-search the graph — 'grep' for entities instead of file lines.

        Matches `pattern` against each entity's name / file / kind / description
        (or a single `field`), returning the matching entities with the field
        that hit and the matched text. This is the graph-native replacement for
        grepping source: full regex power, but over the indexed symbols rather
        than raw text.
        """
        flags = re.IGNORECASE if ignore_case else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as exc:
            return {"pattern": pattern, "error": f"invalid regex: {exc}", "matches": [], "count": 0}

        fields = ["name", "file", "kind", "description"] if field == "all" else [field]
        matches = []
        for _n, a in self.graph.nodes(data=True):
            if a.get("type") != "Entity" or a.get("project") != project:
                continue
            for f in fields:
                val = str(a.get(f) or "")
                m = rx.search(val) if val else None
                if m:
                    matches.append({
                        "name": a.get("name"),
                        "kind": a.get("kind"),
                        "file": a.get("file"),
                        "matched_field": f,
                        "match": m.group(0),
                    })
                    break
            if len(matches) >= limit:
                break
        matches.sort(key=lambda r: (r["file"] or "", r["name"] or ""))
        return {"pattern": pattern, "matches": matches, "count": len(matches)}

    def search_entities(self, query: str, project: str, limit: int = 30,
                        kind: str | None = None) -> list[dict]:
        """Find graph entities matching a keyword — the way in when you don't yet
        know a symbol name.

        Matches the query (case-insensitive) against each entity's name, file
        path, and description. Any term may match (OR), and entities matching
        more terms — and matching in the name rather than file/description — rank
        highest, so the most on-point symbols come first.
        Optional `kind` filters by entity_type (e.g. "function", "class").
        Returns a lean list (name/kind/file/entity_type) to then feed into
        impact/flow/deps.
        """
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return []

        scored = []
        for _id, a in self.graph.nodes(data=True):
            if a.get("type") != "Entity" or a.get("project") != project:
                continue
            if not a.get("file"):
                continue
            if kind and a.get("entity_type") != kind:
                continue
            name = (a.get("name") or "")
            file = (a.get("file") or "")
            desc = (a.get("description") or "")
            hay_name = name.lower()
            hay_rest = f"{file} {desc}".lower()
            # any term may match (OR); score rewards name hits and more terms matched
            score = 0
            for t in terms:
                if t == hay_name:
                    score += 100
                elif t in hay_name:
                    score += 10
                elif t in hay_rest:
                    score += 1
            if score == 0:
                continue
            scored.append((score, {
                "name": name,
                "entity_type": a.get("entity_type", ""),
                "kind": a.get("kind", ""),
                "file": file,
            }))

        scored.sort(key=lambda s: (-s[0], s[1]["file"], s[1]["name"]))
        return [row for _s, row in scored[:limit]]

    def symbol_map(self, project: str, include_tests: bool = False) -> dict:
        """A compact index of the codebase for an agent to reason over.

        Groups every source entity under its file as `{file: [names...]}` —
        names only, no depth/kind/description bloat — so the whole map fits in a
        few thousand tokens. The agent reads it once and uses its own judgment to
        pick what's relevant to a vague task ("where would caching go?"), then
        drills in with impact/flow/deps. This is the semantic-discovery entry
        point that keyword `search` can't be: an LLM knows caching lives near the
        request handler and response path even when nothing is named "cache".

        `include_tests=False` (default) drops test/example files so the map shows
        the actual implementation surface.
        """
        by_file: dict[str, list[str]] = {}
        for _id, a in self.graph.nodes(data=True):
            if a.get("type") != "Entity" or a.get("project") != project:
                continue
            f = a.get("file")
            if not f:
                continue
            if not include_tests and ("test/" in f or "test\\" in f
                                      or f.startswith("test") or "example" in f):
                continue
            name = a.get("name")
            if name:
                by_file.setdefault(f, [])
                if name not in by_file[f]:
                    by_file[f].append(name)
        for f in by_file:
            by_file[f].sort()
        return dict(sorted(by_file.items()))

    def find_dependencies(self, file_path: str, project: str, max_hops: int = 3) -> list[dict]:
        """Return all modules imported (directly or transitively) by file_path."""
        file_node = next((n for n, attr in self.graph.nodes(data=True) 
                         if attr.get("type") == "File" and attr.get("path") == file_path), None)
        if not file_node:
            return []

        results = []
        visited = {file_node}
        queue = [(file_node, 0)]

        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_hops:
                continue
            
            for succ in self.graph.successors(current_id):
                edges = self.graph.get_edge_data(current_id, succ)
                is_relevant = any(edge.get("type") in {"CONTAINS", "IMPORTS"} for edge in edges.values())
                
                if is_relevant and succ not in visited:
                    node = self.graph.nodes[succ]
                    if node.get("type") == "Entity" and any(e.get("type") == "IMPORTS" for e in edges.values()):
                        results.append({
                            "dependency": node.get("name"),
                            "dep_type": node.get("entity_type"),
                            "depth": depth + 1
                        })
                    
                    visited.add(succ)
                    queue.append((succ, depth + 1))
        
        return sorted(results, key=lambda x: (x["depth"], x["dependency"]))

    def find_styles(self, element_name: str, project: str) -> list[dict]:
        """Return all CSS selectors that style element_name."""
        results = []
        for target_id in self._resolve_query_nodes(element_name, project):
            for pred in self.graph.predecessors(target_id):
                edges = self.graph.get_edge_data(pred, target_id)
                for key, edge in edges.items():
                    if edge.get("type") == "STYLES":
                        node = self.graph.nodes[pred]
                        results.append({
                            "selector": node.get("name"),
                            "source_file": node.get("file"),
                            "line": edge.get("line")
                        })

        return sorted(results, key=lambda x: x["selector"])

    def trace_flow(self, start_name: str, project: str, max_hops: int = 6,
                    edge_types: frozenset[str] | None = None,
                    include_external: bool = False) -> dict:
        """BFS from start_name along CALLS/IMPORTS edges. Returns nodes + edges for rendering."""
        if edge_types is None:
            edge_types = frozenset({"CALLS", "IMPORTS"})
        starts = self._resolve_query_nodes(start_name, project)
        if not starts:
            return {"nodes": [], "edges": []}
        start_id = starts[0]

        flow_nodes: dict[str, dict] = {}
        flow_edges: list[dict] = []
        visited = {start_id}
        queue = [(start_id, 0)]

        start_attr = self.graph.nodes[start_id]
        flow_nodes[start_id] = {
            "id": start_id,
            "name": start_attr.get("name", start_name),
            "kind": start_attr.get("kind", ""),
            "description": start_attr.get("description", ""),
            "file": start_attr.get("file", ""),
            "depth": 0,
        }

        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_hops:
                continue
            for succ in self.graph.successors(current_id):
                edge_data = self.graph.get_edge_data(current_id, succ)
                matching = [e for e in edge_data.values() if e.get("type") in edge_types]
                if not matching:
                    continue
                succ_attr = self.graph.nodes[succ]
                if succ_attr.get("type") != "Entity":
                    continue
                if not include_external and not succ_attr.get("file"):
                    continue
                rel_type = matching[0].get("type", "CALLS")
                flow_edges.append({
                    "from": current_id,
                    "to": succ,
                    "type": rel_type,
                    "file": matching[0].get("source_file", ""),
                    "line": matching[0].get("line", ""),
                })
                if succ not in visited:
                    visited.add(succ)
                    flow_nodes[succ] = {
                        "id": succ,
                        "name": succ_attr.get("name", ""),
                        "kind": succ_attr.get("kind", ""),
                        "description": succ_attr.get("description", ""),
                        "file": succ_attr.get("file", ""),
                        "depth": depth + 1,
                    }
                    queue.append((succ, depth + 1))

        return {"nodes": list(flow_nodes.values()), "edges": flow_edges}

    def trace_calls(self, start_name: str, project: str, max_hops: int = 4) -> list[dict]:
        """Trace the call chain forward from start_name up to max_hops deep."""
        starts = self._resolve_query_nodes(start_name, project)
        if not starts:
            return []
        start_id = starts[0]

        results = []
        visited = {start_id}
        queue = [(start_id, 0)]

        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_hops:
                continue
            
            for succ in self.graph.successors(current_id):
                edges = self.graph.get_edge_data(current_id, succ)
                is_relevant = any(edge.get("type") == "CALLS" for edge in edges.values())
                
                if is_relevant and succ not in visited:
                    node = self.graph.nodes[succ]
                    if node.get("type") == "Entity":
                        results.append({
                            "callee_name": node.get("name"),
                            "callee_type": node.get("entity_type"),
                            "callee_file": node.get("file"),
                            "depth": depth + 1
                        })
                        visited.add(succ)
                        queue.append((succ, depth + 1))
                        
        return sorted(results, key=lambda x: (x["depth"], x["callee_name"]))

    def get_project_tree(self, project: str) -> list[dict]:
        """Return the full containment hierarchy for a project."""
        root = next((n for n, attr in self.graph.nodes(data=True) 
                    if attr.get("type") == "Project" and attr.get("name") == project), None)
        if not root:
            return []

        results = []
        queue = [(root, 0)]
        visited = {root}
        
        while queue:
            current_id, depth = queue.pop(0)
            for succ in self.graph.successors(current_id):
                edges = self.graph.get_edge_data(current_id, succ)
                if any(edge.get("type") == "CONTAINS" for edge in edges.values()):
                    node = self.graph.nodes[succ]
                    results.append({
                        "node_type": node.get("type"),
                        "name": node.get("name"),
                        "path": node.get("path"),
                        "depth": depth + 1
                    })
                    if succ not in visited:
                        visited.add(succ)
                        queue.append((succ, depth + 1))
        
        return sorted(results, key=lambda x: (x["depth"], x["path"] or ""))

    def find_dead_code(self, project: str) -> dict:
        """Find entities with no inbound CALLS/IMPORTS/REFERENCES/INHERITS edge.

        Classifies candidates into:
          dead             - private/internal helpers with no caller (high confidence)
          maybe_entrypoint - public names with no static caller; may be invoked
                             via CLI dispatch, a registry, or a framework

        Static analysis only — dynamic dispatch and reflection are invisible, so
        every result is a CANDIDATE to verify, never a guaranteed-dead verdict.
        """
        ref_types = {"CALLS", "IMPORTS", "REFERENCES", "INHERITS"}
        dead, maybe_entry = [], []

        for node_id, attr in self.graph.nodes(data=True):
            if attr.get("type") != "Entity":
                continue
            if attr.get("project") != project:
                continue
            if not attr.get("file"):
                continue  # external/stdlib symbol, not ours to judge

            has_ref = any(
                e.get("type") in ref_types
                for _, _, e in self.graph.in_edges(node_id, data=True)
            )
            if has_ref:
                continue

            name = attr.get("name", "")
            entry = {
                "name": name,
                "kind": attr.get("kind", ""),
                "entity_type": attr.get("entity_type", ""),
                "file": attr.get("file", ""),
            }
            # Exported symbols and name-heuristic entry points are public API:
            # having no in-repo caller is expected, not evidence of dead code.
            if attr.get("is_exported") or _looks_like_entry_point(name, attr.get("entity_type", "")):
                maybe_entry.append(entry)
            else:
                dead.append(entry)

        dead.sort(key=lambda e: (e["file"], e["name"]))
        maybe_entry.sort(key=lambda e: (e["file"], e["name"]))
        return {"dead": dead, "maybe_entrypoint": maybe_entry}

    def get_file_updated_at(self, file_path: str, project: str) -> Optional[str]:
        """Return the updated_at timestamp for a File node, or None if not found."""
        node = next((n for n, attr in self.graph.nodes(data=True) 
                    if attr.get("type") == "File" and attr.get("path") == file_path), None)
        return self.graph.nodes[node].get("updated_at") if node else None

    def get_project_last_ingested(self, project: str) -> Optional[str]:
        """Return the last_ingested timestamp for a Project node, or None if not found."""
        node = next((n for n, attr in self.graph.nodes(data=True) 
                    if attr.get("type") == "Project" and attr.get("name") == project), None)
        return self.graph.nodes[node].get("last_ingested") if node else None

    def get_blast_radius(
        self, target: str, project: str, max_hops: int = 3
    ) -> tuple[list[dict], str | None]:
        """Return every file AFFECTED IF the target changes — its *dependents*.

        Traverses in reverse and transitively: who CALLS/INHERITS/REFERENCES the
        target's symbols, and which files IMPORT the target file (importers of
        importers included). This is the "what breaks if I edit this" direction —
        NOT what the target itself depends on.
        """
        ent_nodes = self._resolve_query_nodes(target, project) if "/" not in target else []
        target_file = None

        if ent_nodes:
            target_file = self.graph.nodes[ent_nodes[0]].get("file")
            start_ids = ent_nodes
            target_files = {self.graph.nodes[n].get("file")
                            for n in ent_nodes if self.graph.nodes[n].get("file")}
        else:
            file_node = next((n for n, attr in self.graph.nodes(data=True)
                             if attr.get("type") == "File" and attr.get("path") == target), None)
            if not file_node:
                return [], None
            target_file = target
            target_files = {target}
            start_ids = [
                succ for succ in self.graph.successors(file_node)
                if any(e.get("type") == "CONTAINS" for e in self.graph.get_edge_data(file_node, succ).values())
                and self.graph.nodes[succ].get("type") == "Entity"
            ]

        dep_types = {"CALLS", "INHERITS", "REFERENCES", "USES_VAR"}
        results = []
        seen_files = set(target_files)  # never report the target's own file(s)

        # 1) Reverse code edges: who calls / inherits / references the symbols.
        visited = set(start_ids)
        queue = [(sid, 0) for sid in start_ids]
        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_hops:
                continue
            for pred in self.graph.predecessors(current_id):
                edges = self.graph.get_edge_data(pred, current_id)
                relevant = {e.get("type") for e in edges.values()} & dep_types
                if not relevant or pred in visited:
                    continue
                visited.add(pred)
                node = self.graph.nodes[pred]
                f = node.get("file")
                if node.get("type") == "Entity" and f and f not in seen_files:
                    results.append({"file": f, "edge_type": next(iter(relevant)), "hops": depth + 1})
                    seen_files.add(f)
                queue.append((pred, depth + 1))

        # 2) Transitive reverse IMPORTS: files importing the target file(s), then
        #    their importers, out to max_hops.
        frontier = set(target_files)
        for hop in range(1, max_hops + 1):
            importers = set()
            for tf in frontier:
                importers.update(self._direct_importers(tf))
            importers -= seen_files
            if not importers:
                break
            for imp in sorted(importers):
                results.append({"file": imp, "edge_type": "IMPORTS", "hops": hop})
                seen_files.add(imp)
            frontier = importers

        return results, target_file

    def _direct_importers(self, target_file: str) -> list[str]:
        """Source files with an IMPORTS edge whose module string resolves to
        target_file. Handles both relative (`./response`) and dotted-module
        (`lib.response`) import spellings."""
        importers: list[str] = []
        for _u, v, data in self.graph.edges(data=True):
            if data.get("type") != "IMPORTS":
                continue
            from_file = data.get("source_file")
            if not from_file:
                continue
            import_str = self.graph.nodes[v].get("name", "")
            if _import_resolves_to(import_str, from_file, target_file):
                importers.append(from_file)
        return sorted(set(importers))

def get_client(project_path: str) -> LocalGraphClient:
    """Return a LocalGraphClient for the project at project_path."""
    storage_path = os.path.join(project_path, ".codecompass", "graph.json")
    return LocalGraphClient(storage_path)
