# Source files are authoritative; this graph is a stale-tolerant index that degrades gracefully.
"""Local graph client for code knowledge graphs.
Replaces Neo4j with NetworkX and JSON persistence.
"""

from __future__ import annotations

import json
import os
import networkx as nx
from datetime import datetime, timezone
from typing import Optional, Any

from models.code_types import CodeTriple, FileNode, FolderNode

# Relationship types emitted by code_parser.
_EXT_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}

_ALLOWED_REL_TYPES = frozenset({
    "CALLS", "IMPORTS", "INHERITS", "DEFINED_IN",
    "HAS_CLASS", "POSTS_TO", "INCLUDES", "STYLES", "USED_BY",
    "USES_VAR", "REFERENCES",
})

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_ENTRY_POINT_PREFIXES = ("run_", "main", "handle_", "cmd_", "test_", "setup_", "teardown_")
_ENTRY_POINT_NAMES = {"main", "__main__", "handler", "lambda_handler", "application", "app"}


def _looks_like_entry_point(name: str, entity_type: str) -> bool:
    """Heuristic: names invoked by a runtime/dispatcher, not by static calls.

    CLI subcommands, request handlers, and test functions have no in-repo caller
    yet are clearly live. Modules are containers, never "dead" in the call sense.
    """
    if entity_type == "module":
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

    def write_code_triple(self, triple: CodeTriple, file_node_id: str, project: str) -> None:
        from_id = f"{project}:{triple.from_entity.lower()}"
        to_id = f"{project}:{triple.to_entity.lower()}"
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
            created_at=_now()
        )

        self.graph.add_edge(file_node_id, from_id, type="CONTAINS")

    def write_code_triples_batch(
        self, 
        triples: list[CodeTriple], 
        file_id_map: dict[str, str], 
        project: str
    ) -> int:
        for triple in triples:
            file_id = file_id_map.get(triple.source_file, "")
            self.write_code_triple(triple, file_id, project)
        
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

    def find_callers(self, entity_name: str, project: str, max_hops: int = 3) -> list[dict]:
        """Return everything that calls/uses/references entity_name (reverse traversal)."""
        target_id = f"{project}:{entity_name.lower()}"
        if target_id not in self.graph:
            return []

        results = []
        visited = {target_id}
        queue = [(target_id, 0)]
        
        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_hops:
                continue
            
            for pred in self.graph.predecessors(current_id):
                edges = self.graph.get_edge_data(pred, current_id)
                is_relevant = any(
                    edge.get("type") in {"CALLS", "USES_VAR", "REFERENCES"} 
                    for edge in edges.values()
                )
                
                if is_relevant and pred not in visited:
                    node = self.graph.nodes[pred]
                    if node.get("type") == "Entity":
                        results.append({
                            "caller_name": node.get("name"),
                            "caller_type": node.get("entity_type"),
                            "caller_file": node.get("file"),
                            "depth": depth + 1
                        })
                        visited.add(pred)
                        queue.append((pred, depth + 1))
        
        return sorted(results, key=lambda x: x["depth"])

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
        target_id = f"{project}:{element_name.lower()}"
        if target_id not in self.graph:
            return []
            
        results = []
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
        start_id = f"{project}:{start_name.lower()}"
        if start_id not in self.graph:
            return {"nodes": [], "edges": []}

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
        start_id = f"{project}:{start_name.lower()}"
        if start_id not in self.graph:
            return []

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
            if _looks_like_entry_point(name, attr.get("entity_type", "")):
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
        """Return all files reachable from target via CALLS/IMPORTS/INHERITS."""
        # Try as entity name first
        entity_id = f"{project}:{target.lower()}"
        target_file = None

        if entity_id in self.graph:
            node = self.graph.nodes[entity_id]
            target_file = node.get("file")
            start_ids = [entity_id]
        else:
            # Try as file path
            file_node = next((n for n, attr in self.graph.nodes(data=True)
                             if attr.get("type") == "File" and attr.get("path") == target), None)
            if not file_node:
                return [], None
            target_file = target
            # Collect all entity children of the file
            start_ids = [
                succ for succ in self.graph.successors(file_node)
                if any(e.get("type") == "CONTAINS" for e in self.graph.get_edge_data(file_node, succ).values())
                and self.graph.nodes[succ].get("type") == "Entity"
            ]

        results = []
        visited = set(start_ids)
        queue = [(sid, 0) for sid in start_ids]

        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_hops:
                continue
            for succ in self.graph.successors(current_id):
                edges = self.graph.get_edge_data(current_id, succ)
                edge_types = {e.get("type") for e in edges.values()}
                relevant = edge_types & {"CALLS", "IMPORTS", "INHERITS"}
                if relevant and succ not in visited:
                    node = self.graph.nodes[succ]
                    if node.get("file"):
                        results.append({
                            "file": node["file"],
                            "edge_type": next(iter(relevant)),
                            "hops": depth + 1
                        })
                    visited.add(succ)
                    queue.append((succ, depth + 1))

        return results, target_file

def get_client(project_path: str) -> LocalGraphClient:
    """Return a LocalGraphClient for the project at project_path."""
    storage_path = os.path.join(project_path, ".codecompass", "graph.json")
    return LocalGraphClient(storage_path)
