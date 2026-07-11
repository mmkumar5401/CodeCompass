from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeTriple:
    """A single typed relationship extracted from source code."""

    from_entity: str
    from_type: str   # function | class | module | css_selector | html_element | scss_mixin | scss_variable |
                      # interface | trait | enum | property | constant
    relation_type: str  # CALLS | IMPORTS | INHERITS | DEFINED_IN | STYLES | HAS_CLASS | POSTS_TO | INCLUDES | USED_BY
    to_entity: str
    to_type: str
    source_file: str  # relative path from project root
    line_number: int

    # Receiver expression text for a member call (`app.handle()` -> "app").
    # None for bare-identifier calls and non-CALLS triples. Lets impact/callers
    # distinguish same-named methods on different receivers (app.handle vs
    # router.handle) instead of silently merging them.
    call_receiver: str | None = None

    # Inferred *type* of the receiver, when statically derivable — from
    # `new Router()`, a TypeScript annotation, or class-method `this`. Enables
    # automatic disambiguation (`impact "Router.handle"` returns only calls on a
    # Router) independent of the local variable name. None when not inferable.
    call_receiver_type: str | None = None

    # True when this DEFINED_IN triple's entity is part of the module's public
    # API (ES `export`, `module.exports`, or a property of the exports object).
    # Lets dead-code analysis avoid flagging intentionally-exported symbols.
    is_exported: bool = False

    # Class that `from_entity` belongs to — the method's class for a definition,
    # or the caller's class for a call. None for module-level entities. Lets node
    # ids be class-qualified so same-named methods of different classes in the
    # SAME file stay distinct (Command.invoke vs Context.invoke in core.py).
    owner_class: str | None = None


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
