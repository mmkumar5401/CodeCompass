"""Database router — Facade over master and per-project Neo4j databases.

Callers specify a scope and get back the right CodeGraphClient without
knowing which database or node-label convention is in use.

Usage:
    client = db_router.get("project:frontend")
    client = db_router.get("master")
    client = db_router.get("auto", seeds=["LoginForm", "AuthService"])
"""

from __future__ import annotations

from typing import Optional

from config import neo4j_config
from graph.code_graph_client import CodeGraphClient

# Database name used for the master graph.
MASTER_DB_NAME = "master"


def get(
    scope: str,
    seeds: Optional[list[str]] = None,
) -> CodeGraphClient:
    """Return a CodeGraphClient routed to the correct database.

    Args:
        scope: One of:
            - "master"             → master cross-project database
            - "project:<name>"     → named project database
            - "auto"               → resolve from seed entity names (requires seeds)
        seeds: Entity names used to auto-resolve the project when scope="auto".

    Raises:
        ValueError: if scope is "auto" but seeds is empty, or scope is unrecognised.
    """
    if scope == "master":
        return _client_for_database(MASTER_DB_NAME)

    if scope.startswith("project:"):
        project_name = scope.removeprefix("project:")
        return _client_for_database(_project_db_name(project_name))

    if scope == "auto":
        return _auto_route(seeds or [])

    raise ValueError(
        f"Unrecognised scope '{scope}'. "
        "Expected 'master', 'project:<name>', or 'auto'."
    )


def project_client(project_name: str) -> CodeGraphClient:
    """Shorthand for get('project:<name>')."""
    return get(f"project:{project_name}")


def master_client() -> CodeGraphClient:
    """Shorthand for get('master')."""
    return get("master")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _client_for_database(database: Optional[str]) -> CodeGraphClient:
    cfg = neo4j_config()
    return CodeGraphClient(
        uri=cfg["uri"],
        user=cfg["user"],
        password=cfg["password"],
        database=database,
    )


def _project_db_name(project_name: str) -> str:
    """Neo4j database names must be lowercase alphanumeric with hyphens."""
    return project_name.lower().replace("_", "-").replace(" ", "-")


def _auto_route(seeds: list[str]) -> CodeGraphClient:
    """Resolve project from seed names by querying the master index.

    Strategy: query master for which project each seed belongs to, then
    return the client for the most-represented project. Falls back to the
    default database if master yields no results.
    """
    if not seeds:
        raise ValueError("scope='auto' requires at least one seed name.")

    master = _client_for_database(MASTER_DB_NAME)
    try:
        rows = master._run_read("""
            MATCH (e:Entity)
            WHERE e.name IN $names
            RETURN e.project AS project, count(*) AS hits
            ORDER BY hits DESC
            LIMIT 1
        """, names=seeds)
    except Exception:
        # Master database may not exist yet (Community edition, first run)
        rows = []
    finally:
        master.close()

    if not rows or not rows[0].get("project"):
        # No match in master — fall back to default database
        return _client_for_database(None)

    return _client_for_database(_project_db_name(rows[0]["project"]))
