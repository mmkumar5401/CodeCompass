# Source files are authoritative; this graph is a stale-tolerant index that degrades gracefully.
"""Neo4j client for code knowledge graphs.

Handles Project / Folder / File / Entity nodes and typed semantic edges
(CALLS, IMPORTS, INHERITS, etc.). Community-edition compatible — filters on
the `project` property instead of requiring separate Neo4j databases.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from neo4j import GraphDatabase

from config import neo4j_config
from models.code_types import CodeTriple, FileNode, FolderNode


# Relationship types emitted by code_parser. Only these are allowed in MERGE
# statements — validated before string interpolation to prevent injection.
_ALLOWED_REL_TYPES = frozenset({
    "CALLS", "IMPORTS", "INHERITS", "DEFINED_IN",
    "HAS_CLASS", "POSTS_TO", "INCLUDES", "STYLES", "USED_BY",
})


def get_client(project: str) -> "CodeGraphClient":
    """Return a CodeGraphClient connected to Neo4j for the given project."""
    cfg = neo4j_config()
    return CodeGraphClient(uri=cfg["uri"], user=cfg["user"], password=cfg["password"])


class CodeGraphClient:
    """Manages code-graph persistence for a single project."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: Optional[str] = None,
    ) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database  # None → Neo4j default (Community compatible)

    # ------------------------------------------------------------------
    # Structural nodes (hierarchy skeleton)
    # ------------------------------------------------------------------

    def merge_project_node(self, node_id: str, name: str, path: str) -> None:
        """Upsert a Project node."""
        self._run("""
            MERGE (p:Project {id: $id})
            SET p.name = $name,
                p.path = $path,
                p.last_ingested = $now
        """, id=node_id, name=name, path=path, now=_now())

    def merge_folder_node(self, node_id: str, folder: FolderNode, project: str) -> None:
        """Upsert a Folder node."""
        self._run("""
            MERGE (f:Folder {id: $id})
            SET f.name = $name,
                f.path = $path,
                f.depth = $depth,
                f.project = $project
        """, id=node_id, name=folder.name, path=folder.path,
             depth=folder.depth, project=project)

    def merge_file_node(self, node_id: str, file: FileNode, project: str) -> None:
        """Upsert a File node, stamping updated_at on every write."""
        self._run("""
            MERGE (f:File {id: $id})
            SET f.name = $name,
                f.path = $path,
                f.extension = $extension,
                f.depth = $depth,
                f.project = $project,
                f.updated_at = $now
        """, id=node_id, name=file.name, path=file.path,
             extension=file.extension, depth=file.depth, project=project,
             now=_now())

    def merge_contains_edge(self, parent_id: str, child_id: str) -> None:
        """Upsert a CONTAINS edge between any two structural nodes."""
        self._run("""
            MATCH (parent {id: $parent_id})
            MATCH (child  {id: $child_id})
            MERGE (parent)-[:CONTAINS]->(child)
        """, parent_id=parent_id, child_id=child_id)

    # ------------------------------------------------------------------
    # Entity nodes and semantic edges (from code triples)
    # ------------------------------------------------------------------

    def write_code_triple(self, triple: CodeTriple, file_node_id: str, project: str) -> None:
        """Persist a CodeTriple as two Entity nodes plus a typed semantic edge.

        Uses whitelist-validated string interpolation for the relationship type
        because Cypher MERGE does not accept parameterised relationship labels.
        """
        from_id = _entity_id(triple.from_entity, project)
        to_id = _entity_id(triple.to_entity, project)

        rel_type = triple.relation_type if triple.relation_type in _ALLOWED_REL_TYPES else "RELATION"

        self._run(f"""
            MERGE (a:Entity {{id: $from_id}})
            SET a.name    = $from_name,
                a.type    = $from_type,
                a.project = $project,
                a.file    = $source_file

            MERGE (b:Entity {{id: $to_id}})
            SET b.name    = $to_name,
                b.type    = $to_type,
                b.project = $project

            MERGE (a)-[r:{rel_type}]->(b)
            ON CREATE SET r.source_file = $source_file,
                          r.line        = $line,
                          r.created_at  = $now
        """,
            from_id=from_id,
            from_name=triple.from_entity,
            from_type=triple.from_type,
            to_id=to_id,
            to_name=triple.to_entity,
            to_type=triple.to_type,
            source_file=triple.source_file,
            line=triple.line_number,
            project=project,
            now=_now(),
        )

        self._run("""
            MATCH (f:File {id: $file_id})
            MATCH (e:Entity {id: $entity_id})
            MERGE (f)-[:CONTAINS]->(e)
        """, file_id=file_node_id, entity_id=from_id)

    # ------------------------------------------------------------------
    # Traversal queries used by code_query_cli
    # ------------------------------------------------------------------

    def find_callers(self, entity_name: str, project: str, max_hops: int = 3) -> list[dict]:
        """Return everything that calls entity_name (reverse CALLS traversal)."""
        entity_id = _entity_id(entity_name, project)
        return self._run_read("""
            MATCH path = (caller:Entity)-[:CALLS*]->(target:Entity {id: $id})
            WHERE caller.project = $project AND length(path) <= $hops
            RETURN caller.name AS caller_name,
                   caller.type AS caller_type,
                   caller.file AS caller_file,
                   length(path) AS depth
            ORDER BY depth
        """, id=entity_id, project=project, hops=max_hops)

    def find_dependencies(self, file_path: str, project: str, max_hops: int = 3) -> list[dict]:
        """Return all modules imported (directly or transitively) by file_path."""
        return self._run_read("""
            MATCH (f:File {path: $path, project: $project})
            MATCH path = (f)-[:CONTAINS]->(:Entity)-[:IMPORTS*]->(dep:Entity)
            WHERE length(path) <= $hops
            RETURN DISTINCT dep.name AS dependency,
                            dep.type AS dep_type,
                            length(path) AS depth
            ORDER BY depth, dep.name
        """, path=file_path, project=project, hops=max_hops)

    def find_styles(self, element_name: str, project: str) -> list[dict]:
        """Return all CSS selectors that style element_name."""
        return self._run_read("""
            MATCH (sel:Entity)-[r:STYLES]->(el:Entity)
            WHERE el.name = $name AND el.project = $project
            RETURN sel.name    AS selector,
                   sel.file    AS source_file,
                   r.line      AS line
            ORDER BY sel.name
        """, name=element_name, project=project)

    def trace_calls(self, start_name: str, project: str, max_hops: int = 4) -> list[dict]:
        """Trace the call chain forward from start_name up to max_hops deep."""
        start_id = _entity_id(start_name, project)
        return self._run_read("""
            MATCH path = (start:Entity {id: $id})-[:CALLS*]->(callee:Entity)
            WHERE callee.project = $project AND length(path) <= $hops
            RETURN callee.name AS callee_name,
                   callee.type AS callee_type,
                   callee.file AS callee_file,
                   length(path) AS depth
            ORDER BY depth, callee.name
        """, id=start_id, project=project, hops=max_hops)

    def get_project_tree(self, project: str) -> list[dict]:
        """Return the full containment hierarchy for a project."""
        return self._run_read("""
            MATCH (root:Project {name: $project})-[:CONTAINS*]->(child)
            RETURN labels(child)[0] AS node_type,
                   child.name      AS name,
                   child.path      AS path,
                   child.depth     AS depth
            ORDER BY child.depth, child.path
        """, project=project)

    def get_file_updated_at(self, file_path: str, project: str) -> Optional[str]:
        """Return the updated_at timestamp for a File node, or None if not found."""
        rows = self._run_read("""
            MATCH (f:File {path: $path, project: $project})
            RETURN f.updated_at AS updated_at
        """, path=file_path, project=project)
        return rows[0]["updated_at"] if rows else None

    def get_project_last_ingested(self, project: str) -> Optional[str]:
        """Return the last_ingested timestamp for a Project node, or None if not found."""
        rows = self._run_read("""
            MATCH (p:Project {name: $project})
            RETURN p.last_ingested AS last_ingested
        """, project=project)
        return rows[0]["last_ingested"] if rows else None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def delete_file_triples(self, file_path: str, project: str) -> None:
        """Remove all Entity nodes sourced from file_path (before re-ingesting a modified file).

        Leaves the File node intact so the hierarchy skeleton remains valid.
        """
        self._run("""
            MATCH (e:Entity {project: $project, file: $path})
            DETACH DELETE e
        """, project=project, path=file_path)

    def delete_file(self, file_path: str, project: str) -> None:
        """Remove both the File node and all Entity nodes sourced from file_path.

        Use for deleted or moved files — removes ghost nodes from the index.
        """
        self._run("""
            MATCH (e:Entity {project: $project, file: $path})
            DETACH DELETE e
        """, project=project, path=file_path)
        self._run("""
            MATCH (f:File {path: $path, project: $project})
            DETACH DELETE f
        """, project=project, path=file_path)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_all_entity_names(self, project: str) -> list[dict]:
        """Return name + id for every entity in a project."""
        return self._run_read("""
            MATCH (e:Entity {project: $project})
            RETURN e.id AS id, e.name AS name, e.type AS entity_type
            ORDER BY e.name
        """, project=project)

    def find_entity_by_name(self, name: str, project: str) -> Optional[dict]:
        """Exact-match lookup for a single entity."""
        rows = self._run_read("""
            MATCH (e:Entity {name: $name, project: $project})
            RETURN e.id AS id, e.name AS name, e.type AS entity_type
            LIMIT 1
        """, name=name, project=project)
        return rows[0] if rows else None

    def get_all_projects(self) -> list[str]:
        """Return the names of all ingested projects, ordered alphabetically."""
        rows = self._run_read("MATCH (p:Project) RETURN p.name AS name ORDER BY p.name")
        return [r["name"] for r in rows]

    def get_file_nodes(self, project: str) -> list[dict]:
        """Return {id, path} for every File node in a project — used by load-triples."""
        return self._run_read("""
            MATCH (f:File {project: $project})
            RETURN f.id AS id, f.path AS path
        """, project=project)

    def node_count(self) -> int:
        """Return total node count across all types."""
        rows = self._run_read("MATCH (n) RETURN count(n) AS cnt")
        return rows[0]["cnt"] if rows else 0

    def close(self) -> None:
        self._driver.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, query: str, **params) -> None:
        try:
            with self._driver.session(database=self._database) as session:
                session.run(query, params)
        except Exception as exc:
            if "DatabaseNotFound" in str(exc) and self._database is not None:
                self._database = None
                with self._driver.session() as session:
                    session.run(query, params)
            else:
                raise

    def _run_read(self, query: str, **params) -> list[dict]:
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(query, params)
                return [record.data() for record in result]
        except Exception as exc:
            if "DatabaseNotFound" in str(exc) and self._database is not None:
                self._database = None
                with self._driver.session() as session:
                    result = session.run(query, params)
                    return [record.data() for record in result]
            raise


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _entity_id(name: str, project: str) -> str:
    """Stable ID scoped to a project — prevents cross-project ID collisions."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{project}:{name.lower()}"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
