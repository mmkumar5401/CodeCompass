"""On-demand source extraction for flow narration.

Given a repo root, a file path, and an entity name, returns the function/class
signature, its docstring, and a trimmed body snippet — pulled live from source
via tree-sitter. This keeps the graph lean (no code stored) while giving agents
the real code they need to describe data flow.
"""

from __future__ import annotations

import os
from pathlib import Path

from ingestion.code_parser import (
    _PARSER_LOADERS,
    _child_of_type,
    _text,
    _walk,
)

# Max characters of body to include per entity so JSON output stays manageable.
_MAX_SNIPPET_CHARS = 1200


def extract_entity_context(repo_root: str, rel_file: str, entity_name: str) -> dict:
    """Return {signature, docstring, snippet, start_line, end_line} for an entity.

    Returns empty strings for fields that can't be resolved. Never raises —
    a missing file or parse failure yields a best-effort empty result.
    """
    result = {
        "signature": "",
        "docstring": "",
        "snippet": "",
        "start_line": None,
        "end_line": None,
    }
    if not rel_file:
        return result

    ext = Path(rel_file).suffix.lower()
    loader = _PARSER_LOADERS.get(ext)
    if loader is None:
        return result

    abs_path = os.path.join(repo_root, rel_file)
    try:
        parser, _lang = loader()
        source = Path(abs_path).read_bytes()
        tree = parser.parse(source)
    except Exception:
        return result

    if ext == ".py":
        node = _find_python_def(tree.root_node, entity_name)
        if node is not None:
            _fill_python(result, node, source)
    elif ext in (".js", ".ts", ".tsx"):
        node = _find_js_def(tree.root_node, entity_name)
        if node is not None:
            _fill_js(result, node, source)

    return result


def _find_python_def(root, name: str):
    for node in _walk(root):
        if node.type in ("function_definition", "class_definition"):
            name_node = _child_of_type(node, "identifier")
            if name_node and _text(name_node) == name:
                return node
    return None


def _find_js_def(root, name: str):
    for node in _walk(root):
        if node.type in ("function_declaration", "function_expression"):
            name_node = _child_of_type(node, "identifier")
            if name_node and _text(name_node) == name:
                return node
        if node.type == "method_definition":
            name_node = _child_of_type(node, "property_identifier")
            if name_node and _text(name_node) == name:
                return node
        if node.type == "variable_declarator":
            name_node = _child_of_type(node, "identifier")
            if name_node and _text(name_node) == name:
                for child in node.children:
                    if child.type in ("arrow_function", "function_expression"):
                        return node
    return None


def _fill_python(result: dict, node, source: bytes) -> None:
    result["start_line"] = node.start_point[0] + 1
    result["end_line"] = node.end_point[0] + 1

    # Signature: everything up to and including the parameter list / superclasses.
    params = _child_of_type(node, "parameters") or _child_of_type(node, "argument_list")
    name_node = _child_of_type(node, "identifier")
    keyword = "def" if node.type == "function_definition" else "class"
    if name_node:
        sig = f"{keyword} {_text(name_node)}"
        if params:
            sig += _text(params)
        result["signature"] = sig.strip()

    body = _child_of_type(node, "block")
    if body is not None:
        result["docstring"] = _python_docstring(body)
        result["snippet"] = _snippet(source, node)


def _fill_js(result: dict, node, source: bytes) -> None:
    result["start_line"] = node.start_point[0] + 1
    result["end_line"] = node.end_point[0] + 1
    params = _child_of_type(node, "formal_parameters")
    name_node = (_child_of_type(node, "identifier")
                 or _child_of_type(node, "property_identifier"))
    if name_node:
        sig = _text(name_node)
        if params:
            sig += _text(params)
        result["signature"] = sig.strip()
    result["snippet"] = _snippet(source, node)


def _python_docstring(block_node) -> str:
    """First string literal in a block is the docstring."""
    for child in block_node.children:
        if child.type == "expression_statement":
            inner = child.children[0] if child.children else None
            if inner is not None and inner.type == "string":
                raw = _text(inner)
                return _clean_docstring(raw)
        # Stop at the first non-docstring statement.
        if child.type not in ("comment", "expression_statement"):
            break
    return ""


def _clean_docstring(raw: str) -> str:
    text = raw.strip()
    for q in ('"""', "'''", '"', "'"):
        if text.startswith(q) and text.endswith(q) and len(text) >= 2 * len(q):
            text = text[len(q):-len(q)]
            break
    return text.strip()


def _snippet(source: bytes, node) -> str:
    raw = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    if len(raw) > _MAX_SNIPPET_CHARS:
        return raw[:_MAX_SNIPPET_CHARS].rstrip() + "\n    # ... (truncated)"
    return raw
