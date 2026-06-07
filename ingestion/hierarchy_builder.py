"""Hierarchy builder — walks a repo and writes the Project → Folder → File skeleton to Neo4j.

This runs before code_parser so every file has a node to attach entities to.
No API calls — purely local filesystem traversal.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from models.code_types import FileNode, FolderNode

# Directory names skipped during traversal
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache",
    "coverage", "tmp", "cache", ".nx", "lcov-report",
}

# Supported source file extensions (mirrors code_parser.SUPPORTED_EXTENSIONS)
_SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".html", ".css", ".scss"}


def build_hierarchy(project_root: str, project_name: str, client) -> dict[str, str]:
    """Walk project_root and write Project → Folder → File nodes to Neo4j.

    Returns a mapping of {relative_file_path: neo4j_node_id} so the caller
    can attach entity nodes to the correct File nodes.

    Args:
        project_root: Absolute path to the repo.
        project_name: Human-readable project identifier (e.g. "frontend").
        client: CodeGraphClient connected to the project's database.
    """
    project_id = _stable_id(f"project:{project_name}")
    client.merge_project_node(project_id, project_name, project_root)

    file_id_map: dict[str, str] = {}

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        rel_dir = os.path.relpath(dirpath, project_root)
        is_root = rel_dir == "."

        if not is_root:
            folder = _make_folder_node(rel_dir, project_root)
            folder_id = _stable_id(f"folder:{project_name}:{folder.path}")
            parent_id = _parent_id(folder, project_name, project_id)
            client.merge_folder_node(folder_id, folder, project_name)
            client.merge_contains_edge(parent_id, folder_id)

        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext not in _SOURCE_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, project_root)
            file = _make_file_node(rel_path, project_root)
            file_id = _stable_id(f"file:{project_name}:{file.path}")

            if is_root:
                parent_node_id = project_id
            else:
                parent_node_id = _stable_id(f"folder:{project_name}:{rel_dir}")

            client.merge_file_node(file_id, file, project_name)
            client.merge_contains_edge(parent_node_id, file_id)
            file_id_map[rel_path] = file_id

    return file_id_map


def collect_file_nodes(project_root: str) -> list[FileNode]:
    """Return FileNode objects for every supported source file under project_root.

    Useful for dry-run inspection or passing file lists to other pipeline stages.
    """
    nodes: list[FileNode] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext in _SOURCE_EXTENSIONS:
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, project_root)
                nodes.append(_make_file_node(rel_path, project_root))
    return nodes


def collect_folder_nodes(project_root: str) -> list[FolderNode]:
    """Return FolderNode objects for every non-skipped directory under project_root."""
    nodes: list[FolderNode] = []
    for dirpath, dirnames, _ in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, project_root)
        if rel_dir != ".":
            nodes.append(_make_folder_node(rel_dir, project_root))
    return nodes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_file_node(rel_path: str, project_root: str) -> FileNode:
    depth = len(Path(rel_path).parts)
    return FileNode(
        path=rel_path,
        name=Path(rel_path).name,
        extension=Path(rel_path).suffix.lower(),
        depth=depth,
    )


def _make_folder_node(rel_dir: str, project_root: str) -> FolderNode:
    depth = len(Path(rel_dir).parts)
    return FolderNode(
        path=rel_dir,
        name=Path(rel_dir).name,
        depth=depth,
    )


def _parent_id(folder: FolderNode, project_name: str, project_id: str) -> str:
    """Return the node ID of the immediate parent of this folder."""
    parent_path = str(Path(folder.path).parent)
    if parent_path == ".":
        return project_id
    return _stable_id(f"folder:{project_name}:{parent_path}")


def _stable_id(key: str) -> str:
    """Deterministic UUID from a string key — same key always produces the same ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))
