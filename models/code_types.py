from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeTriple:
    """A single typed relationship extracted from source code."""

    from_entity: str
    from_type: str   # function | class | module | css_selector | html_element | scss_mixin | scss_variable
    relation_type: str  # CALLS | IMPORTS | INHERITS | DEFINED_IN | STYLES | HAS_CLASS | POSTS_TO | INCLUDES | USED_BY
    to_entity: str
    to_type: str
    source_file: str  # relative path from project root
    line_number: int


@dataclass
class FileNode:
    """Leaf node in the project hierarchy — a single source file."""

    path: str        # relative path from project root
    name: str        # filename without directory
    extension: str   # e.g. ".py", ".ts"
    depth: int       # nesting depth from project root (root files = 1)


@dataclass
class FolderNode:
    """Intermediate node in the project hierarchy."""

    path: str    # relative path from project root
    name: str    # folder name
    depth: int
