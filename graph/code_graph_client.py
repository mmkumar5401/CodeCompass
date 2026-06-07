"""Neo4j client for code knowledge graphs.

Handles Project / Folder / File / Entity nodes and typed semantic edges
(CALLS, IMPORTS, INHERITS, etc.). Operates against a named database so
each project lives in its own Neo4j database when running Enterprise.
Falls back transparently to Community by using the default database and
filtering on the `project` property.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from neo4j import GraphDatabase

from models.code_types import CodeTriple, FileNode, FolderNode


class CodeGraphClient:
    """Manages code-graph persistence for a single project database."""

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
        """Upsert a File node."""
        self._run("""
            MERGE (f:File {id: $id})
            SET f.name = $name,
                f.path = $path,
                f.extension = $extension,
                f.depth = $depth,
                f.project = $project
        """, id=node_id, name=file.name, path=file.path,
             extension=file.extension, depth=file.depth, project=project)

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

        Also writes a DEFINED_IN edge from the from_entity to its file node
        so structural and semantic graphs stay connected.
        """
        from_id = _entity_id(triple.from_entity, project)
        to_id = _entity_id(triple.to_entity, project)

        self._run("""
            MERGE (a:Entity {id: $from_id})
            SET a.name    = $from_name,
                a.type    = $from_type,
                a.project = $project,
                a.file    = $source_file

            MERGE (b:Entity {id: $to_id})
            SET b.name    = $to_name,
                b.type    = $to_type,
                b.project = $project

            MERGE (a)-[r:RELATION {type: $rel_type}]->(b)
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
            rel_type=triple.relation_type,
            source_file=triple.source_file,
            line=triple.line_number,
            project=project,
            now=_now(),
        )

        # Connect entity to its file node in the hierarchy
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
            MATCH path = (caller:Entity)-[:RELATION* {type: 'CALLS'}]->(target:Entity {id: $id})
            WHERE length(path) <= $hops
            RETURN caller.name AS caller_name,
                   caller.type AS caller_type,
                   caller.file AS caller_file,
                   length(path) AS depth
            ORDER BY depth
        """, id=entity_id, hops=max_hops)

    def find_dependencies(self, file_path: str, project: str, max_hops: int = 3) -> list[dict]:
        """Return all modules imported (directly or transitively) by file_path."""
        return self._run_read("""
            MATCH (f:File {path: $path, project: $project})
            MATCH path = (f)-[:CONTAINS]->(:Entity)-[:RELATION* {type: 'IMPORTS'}]->(dep:Entity)
            WHERE length(path) <= $hops
            RETURN DISTINCT dep.name AS dependency,
                            dep.type AS dep_type,
                            length(path) AS depth
            ORDER BY depth, dep.name
        """, path=file_path, project=project, hops=max_hops)

    def find_styles(self, element_name: str, project: str) -> list[dict]:
        """Return all CSS selectors that style element_name."""
        return self._run_read("""
            MATCH (sel:Entity)-[r:RELATION {type: 'STYLES'}]->(el:Entity)
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
            MATCH path = (start:Entity {id: $id})-[:RELATION* {type: 'CALLS'}]->(callee:Entity)
            WHERE length(path) <= $hops
            RETURN callee.name AS callee_name,
                   callee.type AS callee_type,
                   callee.file AS callee_file,
                   length(path) AS depth
            ORDER BY depth, callee.name
        """, id=start_id, hops=max_hops)

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

    # ------------------------------------------------------------------
    # Master graph — cross-project bridge edges
    # ------------------------------------------------------------------

    def write_bridge_edge(
        self,
        from_entity_id: str,
        to_entity_id: str,
        bridge_type: str,
        confidence: float,
        via: str,
    ) -> None:
        """Persist a cross-project BRIDGE edge."""
        self._run("""
            MATCH (a:Entity {id: $from_id})
            MATCH (b:Entity {id: $to_id})
            MERGE (a)-[br:BRIDGE]->(b)
            ON CREATE SET br.type        = $bridge_type,
                          br.confidence  = $confidence,
                          br.via         = $via,
                          br.detected_at = $now
            ON MATCH  SET br.confidence  = $confidence,
                          br.via         = $via
        """,
            from_id=from_entity_id,
            to_id=to_entity_id,
            bridge_type=bridge_type,
            confidence=confidence,
            via=via,
            now=_now(),
        )

    def get_all_entity_names(self, project: str) -> list[dict]:
        """Return name + id for every entity in a project — used by bridge_detector."""
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

    def delete_file_triples(self, file_path: str, project: str) -> None:
        """Remove all Entity nodes and RELATION edges sourced from file_path.

        Used by file_watcher before re-ingesting a changed file.
        """
        self._run("""
            MATCH (e:Entity {project: $project, file: $path})
            DETACH DELETE e
        """, project=project, path=file_path)

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
                # Community edition — silently fall back to the default database
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
