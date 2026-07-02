"""Tree-sitter-based code parser.

Parses source files locally (no API calls) into typed CodeTriples.
Uses direct AST node walking — compatible with any tree-sitter version.

Supports: .py, .js, .jsx, .ts, .tsx, .html, .css, .scss, .php
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

from tree_sitter import Language, Parser, Node

from models.code_types import CodeTriple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".php"}

# Relation types
DEFINED_IN = "DEFINED_IN"
CALLS = "CALLS"
INHERITS = "INHERITS"
IMPORTS = "IMPORTS"
HAS_CLASS = "HAS_CLASS"
POSTS_TO = "POSTS_TO"
INCLUDES = "INCLUDES"
STYLES = "STYLES"
USED_BY = "USED_BY"
USES_VAR = "USES_VAR"
REFERENCES = "REFERENCES"

# Entity types
TYPE_FUNCTION = "function"
TYPE_CLASS = "class"
TYPE_MODULE = "module"
TYPE_CSS_SELECTOR = "css_selector"
TYPE_HTML_ELEMENT = "html_element"
TYPE_SCSS_MIXIN = "scss_mixin"
TYPE_SCSS_VARIABLE = "scss_variable"
TYPE_ENDPOINT = "endpoint"
TYPE_CSS_CLASS = "css_class"
TYPE_FILE = "file"
TYPE_INTERFACE = "interface"
TYPE_TRAIT = "trait"
TYPE_ENUM = "enum"
TYPE_PROPERTY = "property"
TYPE_CONSTANT = "constant"

# PHP pseudo-class references that never resolve to a real, distinct entity.
_PHP_SELF_REFERENTIAL = {"self", "static", "parent"}

# Container node types that own PHP class-body members (properties, consts,
# trait uses), mapped to the entity type of the container itself.
_PHP_CONTAINER_TYPES = {
    "class_declaration": TYPE_CLASS,
    "trait_declaration": TYPE_TRAIT,
    "interface_declaration": TYPE_INTERFACE,
    "enum_declaration": TYPE_ENUM,
}

# Regex patterns for CSS/SCSS source scanning
_CSS_VAR_RE = re.compile(r'var\(\s*(--[\w-]+)')
_SCSS_IMPORT_RE = re.compile(r'@(?:import|use|forward)\s+["\']([^"\']+)["\']', re.MULTILINE)

# Regex patterns for Lit css`...` tagged template literals in .styles.ts files
_LIT_CSS_TEMPLATE_RE = re.compile(r'css`(.*?)`', re.DOTALL)
_TEMPLATE_EXPR_RE = re.compile(r'\$\{[^}]*\}')          # strips ${...} interpolations
_CSS_CUSTOM_PROP_RE = re.compile(r'(--[\w-]+)\s*:')      # CSS custom property declarations

# Built-in names that add no signal as CALLS targets
_NOISE_CALLEES = {
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "super", "type", "isinstance", "hasattr", "getattr",
    "setattr", "open", "zip", "map", "filter", "enumerate", "sorted",
    "reversed", "min", "max", "sum", "any", "all", "repr", "format",
    "append", "extend", "update", "items", "keys", "values", "get",
}


# ---------------------------------------------------------------------------
# Language loader helpers (lazy — only import what's installed)
# ---------------------------------------------------------------------------

def _make_parser(language_callable) -> tuple[Parser, Language]:
    lang = Language(language_callable())
    return Parser(lang), lang


def _load_python_parser() -> tuple[Parser, Language]:
    import tree_sitter_python as tsp
    return _make_parser(tsp.language)


def _load_javascript_parser() -> tuple[Parser, Language]:
    import tree_sitter_javascript as tsjs
    return _make_parser(tsjs.language)


def _load_typescript_parser() -> tuple[Parser, Language]:
    import tree_sitter_typescript as tsts
    return _make_parser(tsts.language_typescript)


def _load_tsx_parser() -> tuple[Parser, Language]:
    import tree_sitter_typescript as tsts
    return _make_parser(tsts.language_tsx)


def _load_html_parser() -> tuple[Parser, Language]:
    import tree_sitter_html as tshtml
    return _make_parser(tshtml.language)


def _load_php_parser() -> tuple[Parser, Language]:
    import tree_sitter_php as tsphp
    return _make_parser(tsphp.language_php)


def _load_css_parser() -> tuple[Parser, Language]:
    import tree_sitter_css as tscss
    return _make_parser(tscss.language)


_PARSER_LOADERS: dict[str, Callable[[], tuple[Parser, Language]]] = {
    ".py":   _load_python_parser,
    ".js":   _load_javascript_parser,
    ".jsx":  _load_javascript_parser,
    ".ts":   _load_typescript_parser,
    ".tsx":  _load_tsx_parser,
    ".html": _load_html_parser,
    ".css":  _load_css_parser,
    ".scss": _load_css_parser,
    ".php":  _load_php_parser,
}


# ---------------------------------------------------------------------------
# Generic AST walker
# ---------------------------------------------------------------------------

def _walk(node: Node) -> list[Node]:
    """Yield node and all its descendants depth-first."""
    stack = [node]
    result = []
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(reversed(current.children))
    return result


def _text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace") if node.text else ""


def _line(node: Node) -> int:
    return node.start_point[0] + 1  # tree-sitter uses 0-based rows


def _child_of_type(node: Node, type_name: str) -> Node | None:
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _get_node_name(node: Node, types: list[str]) -> str | None:
    """Try multiple type names to find an identifier/name node."""
    for t in types:
        found = _child_of_type(node, t)
        if found:
            return _text(found)
    return None


def _children_of_type(node: Node, type_name: str) -> list[Node]:
    return [c for c in node.children if c.type == type_name]


# ---------------------------------------------------------------------------
# Python extraction
# ---------------------------------------------------------------------------

def _enclosing_scope(node: Node) -> str | None:
    """Walk up from node to find the nearest enclosing function or class name."""
    current = node.parent
    while current:
        if current.type in ("function_definition", "class_definition"):
            name_node = _child_of_type(current, "identifier")
            if name_node:
                return _text(name_node)
        current = current.parent
    return None


def _extract_python(root: Node, source: bytes, file_path: str) -> list[CodeTriple]:
    module_name = _module_name_from_path(file_path)
    triples: list[CodeTriple] = []

    for node in _walk(root):
        match node.type:
            case "function_definition":
                name = _get_node_name(node, ["identifier"])
                if name:
                    triples.append(CodeTriple(
                        from_entity=name,
                        from_type=TYPE_FUNCTION,
                        relation_type=DEFINED_IN,
                        to_entity=module_name,
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(node),
                    ))

            case "class_definition":
                name = _get_node_name(node, ["identifier"])
                if not name:
                    continue
                class_name = name

                # Extract base classes from argument_list
                arg_list = _child_of_type(node, "argument_list")
                if arg_list:
                    for base in _children_of_type(arg_list, "identifier"):
                        triples.append(CodeTriple(
                            from_entity=class_name,
                            from_type=TYPE_CLASS,
                            relation_type=INHERITS,
                            to_entity=_text(base),
                            to_type=TYPE_CLASS,
                            source_file=file_path,
                            line_number=_line(base),
                        ))

            case "import_statement":
                for dotted in _children_of_type(node, "dotted_name"):
                    triples.append(CodeTriple(
                        from_entity=module_name,
                        from_type=TYPE_MODULE,
                        relation_type=IMPORTS,
                        to_entity=_text(dotted),
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(dotted),
                    ))
                for alias in _children_of_type(node, "aliased_import"):
                    dotted = _child_of_type(alias, "dotted_name")
                    if dotted:
                        triples.append(CodeTriple(
                            from_entity=module_name,
                            from_type=TYPE_MODULE,
                            relation_type=IMPORTS,
                            to_entity=_text(dotted),
                            to_type=TYPE_MODULE,
                            source_file=file_path,
                            line_number=_line(dotted),
                        ))

            case "import_from_statement":
                module_node = _child_of_type(node, "dotted_name")
                if module_node:
                    triples.append(CodeTriple(
                        from_entity=module_name,
                        from_type=TYPE_MODULE,
                        relation_type=IMPORTS,
                        to_entity=_text(module_node),
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(module_node),
                    ))

            case "call":
                callee = _extract_python_callee(node)
                if callee and _is_meaningful_callee(callee):
                    scope = _enclosing_scope(node)
                    caller = scope or module_name
                    caller_type = TYPE_FUNCTION if scope else TYPE_MODULE
                    triples.append(CodeTriple(
                        from_entity=caller,
                        from_type=caller_type,
                        relation_type=CALLS,
                        to_entity=callee,
                        to_type=TYPE_FUNCTION,
                        source_file=file_path,
                        line_number=_line(node),
                    ))

    return triples


def _extract_python_callee(call_node: Node) -> str | None:
    """Extract the callee name from a `call` node."""
    # First child is the function expression
    if not call_node.children:
        return None
    fn_node = call_node.children[0]
    if fn_node.type == "identifier":
        return _text(fn_node)
    if fn_node.type == "attribute":
        # `obj.method` — the attribute being called is the LAST identifier,
        # not the object it's accessed on (e.g. pipeline.submit → "submit").
        attr = fn_node.child_by_field_name("attribute")
        if attr is None:
            idents = [c for c in fn_node.children if c.type == "identifier"]
            attr = idents[-1] if idents else None
        return _text(attr) if attr else None
    return None


# ---------------------------------------------------------------------------
# PHP extraction
# ---------------------------------------------------------------------------
#
# Node-type names below were verified against tree_sitter_php 0.24.1 by
# parsing representative snippets and inspecting the resulting AST directly
# (the grammar ships no node-types.json in the pip package). Names differ
# substantially from other PHP tree-sitter grammar versions found online —
# e.g. classes are `class_declaration` (not `class_definition`), function
# calls are `function_call_expression` (not `function_call`), and name
# fields are typed `name` (not `identifier`).

def _php_name(node: Node) -> str | None:
    """Direct `name` child — used for the declared name of most PHP nodes."""
    found = _child_of_type(node, "name")
    return _text(found) if found else None


def _php_basename(node: Node) -> str:
    """Strip a namespace prefix: `App\\Models\\Foo` -> `Foo`. Also handles a
    bare `name` node (no backslash) and a leading-backslash FQN (`\\Foo`)."""
    return _text(node).rsplit("\\", 1)[-1]


def _php_dotted(node: Node) -> str:
    """Namespace-qualified name -> dotted form, matching the module-name
    convention used elsewhere (`App\\Models\\Foo` -> `App.Models.Foo`)."""
    return _text(node).lstrip("\\").replace("\\", ".")


def _php_var_name(node: Node) -> str:
    """`variable_name` node text (`$name`) -> bare name (`name`)."""
    return _text(node).lstrip("$")


def _php_extends_targets(clause: Node) -> list[Node]:
    """`name`/`qualified_name` children of a base_clause or interface clause.

    Handles both single-target class `extends` and multi-target interface
    `extends`/`implements` (comma-separated siblings, not a nested list).
    """
    return [c for c in clause.children if c.type in ("name", "qualified_name")]


def _enclosing_php_container(node: Node) -> tuple[str, str] | None:
    """Walk up to the nearest enclosing class/trait/interface/enum.

    Used to attach properties, constants, and trait-uses to their owner.
    """
    current = node.parent
    while current:
        entity_type = _PHP_CONTAINER_TYPES.get(current.type)
        if entity_type:
            name = _php_name(current)
            if name:
                return name, entity_type
        current = current.parent
    return None


def _enclosing_php_scope(node: Node) -> tuple[str, str] | None:
    """Walk up from node to find the nearest enclosing function/method/closure.

    Closures (anonymous_function, arrow_function) only count as a scope if
    assigned to a variable (`$fn = function() {...}`), whose name is then
    used as the caller entity; unnamed inline closures are transparent and
    resolution continues further up the tree.
    """
    current = node.parent
    while current:
        if current.type in ("function_definition", "method_declaration"):
            name = _php_name(current)
            if name:
                return name, TYPE_FUNCTION
        elif current.type in ("anonymous_function", "arrow_function"):
            parent = current.parent
            if parent and parent.type == "assignment_expression" and parent.children:
                lhs = parent.children[0]
                if lhs.type == "variable_name":
                    return _php_var_name(lhs), TYPE_FUNCTION
        current = current.parent
    return None


def _extract_php_namespace_use(node: Node) -> list[tuple[str, Node]]:
    """Resolve every imported target of a `use ...;` statement to a dotted
    name plus the node to attribute the line number to.

    Handles plain (`use App\\Foo;`), aliased (`use App\\Foo as F;`), grouped
    (`use App\\{Bar, Baz as Z};`), and `use function`/`use const` forms.
    """
    results: list[tuple[str, Node]] = []
    group = _child_of_type(node, "namespace_use_group")
    if group is not None:
        prefix_node = _child_of_type(node, "namespace_name")
        prefix = _text(prefix_node) if prefix_node else ""
        for clause in _children_of_type(group, "namespace_use_clause"):
            target = _child_of_type(clause, "qualified_name") or _child_of_type(clause, "name")
            if target:
                full = f"{prefix}\\{_text(target)}" if prefix else _text(target)
                results.append((full.lstrip("\\").replace("\\", "."), target))
    else:
        for clause in _children_of_type(node, "namespace_use_clause"):
            target = _child_of_type(clause, "qualified_name") or _child_of_type(clause, "name")
            if target:
                results.append((_php_dotted(target), target))
    return results


def _php_include_target(node: Node) -> Node | None:
    """The literal string argument of a require/include expression, if any.

    Dynamic paths (`require __DIR__ . '/x.php';`) have no plain `string`
    child and are skipped — no static target to record.
    """
    return _child_of_type(node, "string")


def _php_string_text(string_node: Node) -> str:
    frag = _child_of_type(string_node, "string_content")
    return _text(frag) if frag else _text(string_node).strip("'\"")


def _extract_php(root: Node, source: bytes, file_path: str) -> list[CodeTriple]:
    module_name = _module_name_from_path(file_path)
    triples: list[CodeTriple] = []

    def defined_in(name: str, entity_type: str, line: int) -> None:
        triples.append(CodeTriple(
            from_entity=name,
            from_type=entity_type,
            relation_type=DEFINED_IN,
            to_entity=module_name,
            to_type=TYPE_MODULE,
            source_file=file_path,
            line_number=line,
        ))

    def inherits(from_name: str, from_type: str, to_node: Node, to_type: str) -> None:
        basename = _php_basename(to_node)
        if basename and basename.lower() not in _PHP_SELF_REFERENTIAL:
            triples.append(CodeTriple(
                from_entity=from_name,
                from_type=from_type,
                relation_type=INHERITS,
                to_entity=basename,
                to_type=to_type,
                source_file=file_path,
                line_number=_line(to_node),
            ))

    def calls(callee: str, callee_type: str, line: int, scope_node: Node) -> None:
        if not callee or not _is_meaningful_callee(callee):
            return
        scope = _enclosing_php_scope(scope_node)
        caller, caller_type = scope if scope else (module_name, TYPE_MODULE)
        triples.append(CodeTriple(
            from_entity=caller,
            from_type=caller_type,
            relation_type=CALLS,
            to_entity=callee,
            to_type=callee_type,
            source_file=file_path,
            line_number=line,
        ))

    for node in _walk(root):
        match node.type:
            # -- Functions -----------------------------------------------
            case "function_definition":
                name = _php_name(node)
                if name:
                    defined_in(name, TYPE_FUNCTION, _line(node))

            case "method_declaration":
                name = _php_name(node)
                if name:
                    defined_in(name, TYPE_FUNCTION, _line(node))

            case "anonymous_function" | "arrow_function":
                parent = node.parent
                if parent and parent.type == "assignment_expression" and parent.children:
                    lhs = parent.children[0]
                    if lhs.type == "variable_name":
                        defined_in(_php_var_name(lhs), TYPE_FUNCTION, _line(node))

            # -- Classes / interfaces / traits / enums --------------------
            case "class_declaration":
                name = _php_name(node)
                if not name:
                    continue
                defined_in(name, TYPE_CLASS, _line(node))
                base_clause = _child_of_type(node, "base_clause")
                if base_clause:
                    for target in _php_extends_targets(base_clause):
                        inherits(name, TYPE_CLASS, target, TYPE_CLASS)
                iface_clause = _child_of_type(node, "class_interface_clause")
                if iface_clause:
                    for target in _php_extends_targets(iface_clause):
                        inherits(name, TYPE_CLASS, target, TYPE_INTERFACE)

            case "interface_declaration":
                name = _php_name(node)
                if not name:
                    continue
                defined_in(name, TYPE_INTERFACE, _line(node))
                base_clause = _child_of_type(node, "base_clause")
                if base_clause:
                    for target in _php_extends_targets(base_clause):
                        inherits(name, TYPE_INTERFACE, target, TYPE_INTERFACE)

            case "trait_declaration":
                name = _php_name(node)
                if name:
                    defined_in(name, TYPE_TRAIT, _line(node))

            case "enum_declaration":
                name = _php_name(node)
                if not name:
                    continue
                defined_in(name, TYPE_ENUM, _line(node))
                iface_clause = _child_of_type(node, "class_interface_clause")
                if iface_clause:
                    for target in _php_extends_targets(iface_clause):
                        inherits(name, TYPE_ENUM, target, TYPE_INTERFACE)

            case "enum_case":
                container = _enclosing_php_container(node)
                name = _php_name(node)
                if name and container:
                    container_name, container_type = container
                    triples.append(CodeTriple(
                        from_entity=name,
                        from_type=TYPE_CONSTANT,
                        relation_type=DEFINED_IN,
                        to_entity=container_name,
                        to_type=container_type,
                        source_file=file_path,
                        line_number=_line(node),
                    ))

            # -- Trait usage inside a class/trait body --------------------
            case "use_declaration":
                container = _enclosing_php_container(node)
                if container:
                    container_name, container_type = container
                    for target in _children_of_type(node, "name"):
                        triples.append(CodeTriple(
                            from_entity=container_name,
                            from_type=container_type,
                            relation_type=INHERITS,
                            to_entity=_text(target),
                            to_type=TYPE_TRAIT,
                            source_file=file_path,
                            line_number=_line(target),
                        ))

            # -- Namespace imports -----------------------------------------
            case "namespace_use_declaration":
                for dotted, target_node in _extract_php_namespace_use(node):
                    triples.append(CodeTriple(
                        from_entity=module_name,
                        from_type=TYPE_MODULE,
                        relation_type=IMPORTS,
                        to_entity=dotted,
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(target_node),
                    ))

            # -- require/include -------------------------------------------
            case "require_once_expression" | "require_expression" | "include_expression" | "include_once_expression":
                str_node = _php_include_target(node)
                if str_node:
                    triples.append(CodeTriple(
                        from_entity=module_name,
                        from_type=TYPE_MODULE,
                        relation_type=INCLUDES,
                        to_entity=_php_string_text(str_node),
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(str_node),
                    ))

            # -- Properties / constructor-promoted properties ---------------
            case "property_declaration":
                container = _enclosing_php_container(node)
                if container:
                    container_name, container_type = container
                    for element in _children_of_type(node, "property_element"):
                        var_node = _child_of_type(element, "variable_name")
                        if var_node:
                            triples.append(CodeTriple(
                                from_entity=_php_var_name(var_node),
                                from_type=TYPE_PROPERTY,
                                relation_type=DEFINED_IN,
                                to_entity=container_name,
                                to_type=container_type,
                                source_file=file_path,
                                line_number=_line(var_node),
                            ))

            case "property_promotion_parameter":
                container = _enclosing_php_container(node)
                var_node = _child_of_type(node, "variable_name")
                if container and var_node:
                    container_name, container_type = container
                    triples.append(CodeTriple(
                        from_entity=_php_var_name(var_node),
                        from_type=TYPE_PROPERTY,
                        relation_type=DEFINED_IN,
                        to_entity=container_name,
                        to_type=container_type,
                        source_file=file_path,
                        line_number=_line(var_node),
                    ))

            # -- Constants (class/interface/trait/enum or top-level) -------
            case "const_declaration":
                container = _enclosing_php_container(node)
                for element in _children_of_type(node, "const_element"):
                    name_node = _child_of_type(element, "name")
                    if not name_node:
                        continue
                    to_entity, to_type = container if container else (module_name, TYPE_MODULE)
                    triples.append(CodeTriple(
                        from_entity=_text(name_node),
                        from_type=TYPE_CONSTANT,
                        relation_type=DEFINED_IN,
                        to_entity=to_entity,
                        to_type=to_type,
                        source_file=file_path,
                        line_number=_line(name_node),
                    ))

            # -- Calls -------------------------------------------------------
            case "function_call_expression":
                callee_node = _child_of_type(node, "name") or _child_of_type(node, "qualified_name")
                if callee_node:
                    calls(_php_basename(callee_node), TYPE_FUNCTION, _line(node), node)

            case "member_call_expression" | "nullsafe_member_call_expression":
                callee_node = _child_of_type(node, "name")
                if callee_node:
                    calls(_text(callee_node), TYPE_FUNCTION, _line(node), node)

            case "scoped_call_expression":
                names = _children_of_type(node, "name")
                if names:
                    calls(_text(names[-1]), TYPE_FUNCTION, _line(node), node)

            case "object_creation_expression":
                class_node = None
                for child in node.children:
                    if child.type in ("name", "qualified_name"):
                        class_node = child
                        break
                if class_node:
                    basename = _php_basename(class_node)
                    if basename.lower() not in _PHP_SELF_REFERENTIAL:
                        calls(basename, TYPE_CLASS, _line(node), node)

    return triples

# ---------------------------------------------------------------------------
# JavaScript / TypeScript extraction
# ---------------------------------------------------------------------------

def _extract_javascript(root: Node, source: bytes, file_path: str) -> list[CodeTriple]:
    module_name = _module_name_from_path(file_path)
    triples: list[CodeTriple] = []

    for node in _walk(root):
        match node.type:
            case "function_declaration" | "function_expression":
                name_node = _child_of_type(node, "identifier")
                if name_node:
                    triples.append(CodeTriple(
                        from_entity=_text(name_node),
                        from_type=TYPE_FUNCTION,
                        relation_type=DEFINED_IN,
                        to_entity=module_name,
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(name_node),
                    ))

            case "method_definition":
                name_node = _child_of_type(node, "property_identifier")
                if name_node:
                    triples.append(CodeTriple(
                        from_entity=_text(name_node),
                        from_type=TYPE_FUNCTION,
                        relation_type=DEFINED_IN,
                        to_entity=module_name,
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(name_node),
                    ))

            case "variable_declarator":
                # Capture: const foo = () => ...
                value = None
                for child in node.children:
                    if child.type in ("arrow_function", "function_expression"):
                        value = child
                        break
                if value:
                    name_node = _child_of_type(node, "identifier")
                    if name_node:
                        triples.append(CodeTriple(
                            from_entity=_text(name_node),
                            from_type=TYPE_FUNCTION,
                            relation_type=DEFINED_IN,
                            to_entity=module_name,
                            to_type=TYPE_MODULE,
                            source_file=file_path,
                            line_number=_line(name_node),
                        ))

            case "import_statement":
                source_node = _child_of_type(node, "string")
                if source_node:
                    # string → string_fragment (inner text without quotes)
                    frag = _child_of_type(source_node, "string_fragment")
                    module_text = _text(frag) if frag else _text(source_node).strip("'\"`")
                    triples.append(CodeTriple(
                        from_entity=module_name,
                        from_type=TYPE_MODULE,
                        relation_type=IMPORTS,
                        to_entity=module_text,
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(source_node),
                    ))

            case "call_expression":
                callee = _extract_js_callee(node)
                if callee and _is_meaningful_callee(callee):
                    scope = _enclosing_js_scope(node)
                    caller = scope or module_name
                    caller_type = TYPE_FUNCTION if scope else TYPE_MODULE
                    triples.append(CodeTriple(
                        from_entity=caller,
                        from_type=caller_type,
                        relation_type=CALLS,
                        to_entity=callee,
                        to_type=TYPE_FUNCTION,
                        source_file=file_path,
                        line_number=_line(node),
                    ))

    return triples


def _enclosing_js_scope(node: Node) -> str | None:
    """Walk up from node to find the nearest enclosing function name in JS/TS."""
    current = node.parent
    while current:
        if current.type in ("function_declaration", "function_expression"):
            name_node = _child_of_type(current, "identifier")
            if name_node:
                return _text(name_node)
        elif current.type == "method_definition":
            name_node = _child_of_type(current, "property_identifier")
            if name_node:
                return _text(name_node)
        elif current.type == "variable_declarator":
            for child in current.children:
                if child.type in ("arrow_function", "function_expression"):
                    name_node = _child_of_type(current, "identifier")
                    if name_node:
                        return _text(name_node)
                    break
        current = current.parent
    return None


def _extract_js_callee(call_node: Node) -> str | None:
    if not call_node.children:
        return None
    fn_node = call_node.children[0]
    if fn_node.type == "identifier":
        return _text(fn_node)
    if fn_node.type == "member_expression":
        prop = _child_of_type(fn_node, "property_identifier")
        return _text(prop) if prop else None
    return None


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

def _extract_html(root: Node, source: bytes, file_path: str) -> list[CodeTriple]:
    component_name = Path(file_path).stem
    triples: list[CodeTriple] = []
    seen_tags: set[str] = set()

    for node in _walk(root):
        # Index custom element tag references (<a-button>, <tm-icon>, etc.)
        # Custom elements always contain a hyphen per the HTML spec.
        if node.type == "start_tag":
            tag_node = _child_of_type(node, "tag_name")
            if tag_node:
                tag_name = _text(tag_node)
                if "-" in tag_name and tag_name not in seen_tags:
                    seen_tags.add(tag_name)
                    triples.append(CodeTriple(
                        from_entity=component_name,
                        from_type=TYPE_HTML_ELEMENT,
                        relation_type=REFERENCES,
                        to_entity=tag_name,
                        to_type=TYPE_HTML_ELEMENT,
                        source_file=file_path,
                        line_number=_line(tag_node),
                    ))

        if node.type != "attribute":
            continue

        name_node = _child_of_type(node, "attribute_name")
        value_node = _child_of_type(node, "quoted_attribute_value")
        if not name_node or not value_node:
            continue

        attr_name = _text(name_node).lower()
        # quoted_attribute_value → attribute_value (inner text)
        inner = _child_of_type(value_node, "attribute_value")
        attr_value = _text(inner) if inner else _text(value_node).strip("\"'")

        if attr_name == "class":
            for css_class in attr_value.split():
                triples.append(CodeTriple(
                    from_entity=component_name,
                    from_type=TYPE_HTML_ELEMENT,
                    relation_type=HAS_CLASS,
                    to_entity=css_class,
                    to_type=TYPE_CSS_CLASS,
                    source_file=file_path,
                    line_number=_line(name_node),
                ))

        elif attr_name == "action":
            triples.append(CodeTriple(
                from_entity=component_name,
                from_type=TYPE_HTML_ELEMENT,
                relation_type=POSTS_TO,
                to_entity=attr_value,
                to_type=TYPE_ENDPOINT,
                source_file=file_path,
                line_number=_line(name_node),
            ))

        elif attr_name == "src" and attr_value.endswith((".js", ".ts")):
            triples.append(CodeTriple(
                from_entity=component_name,
                from_type=TYPE_HTML_ELEMENT,
                relation_type=INCLUDES,
                to_entity=attr_value,
                to_type=TYPE_MODULE,
                source_file=file_path,
                line_number=_line(name_node),
            ))

    return triples


# ---------------------------------------------------------------------------
# CSS / SCSS extraction
# ---------------------------------------------------------------------------

def _extract_css(root: Node, source: bytes, file_path: str) -> list[CodeTriple]:
    file_name = Path(file_path).name
    is_scss = file_path.endswith(".scss")
    module_name = _module_name_from_path(file_path)
    triples: list[CodeTriple] = []

    for node in _walk(root):
        if node.type == "rule_set":
            selectors_node = _child_of_type(node, "selectors")
            if not selectors_node:
                continue
            selector_text = _text(selectors_node).strip()

            # Extract bare element names from the selector string
            for part in selector_text.split():
                element = part.strip(",>+~")
                if element and not element.startswith((".", "#", "&", "@", ":", "[")):
                    if element.replace("-", "").isalpha():
                        triples.append(CodeTriple(
                            from_entity=selector_text,
                            from_type=TYPE_CSS_SELECTOR,
                            relation_type=STYLES,
                            to_entity=element,
                            to_type=TYPE_HTML_ELEMENT,
                            source_file=file_path,
                            line_number=_line(selectors_node),
                        ))

        elif node.type == "declaration":
            prop_node = _child_of_type(node, "property_name")
            if prop_node:
                prop = _text(prop_node)
                if prop.startswith("--") or (is_scss and prop.startswith("$")):
                    triples.append(CodeTriple(
                        from_entity=prop,
                        from_type=TYPE_SCSS_VARIABLE,
                        relation_type=DEFINED_IN,
                        to_entity=file_name,
                        to_type=TYPE_FILE,
                        source_file=file_path,
                        line_number=_line(prop_node),
                    ))

    # Scan source text for var(--foo) usages — emit one USES_VAR triple per unique variable.
    source_text = source.decode("utf-8", errors="replace")
    seen_vars: set[str] = set()
    for match in _CSS_VAR_RE.finditer(source_text):
        var_name = match.group(1)
        if var_name in seen_vars:
            continue
        seen_vars.add(var_name)
        line = source_text[: match.start()].count("\n") + 1
        triples.append(CodeTriple(
            from_entity=module_name,
            from_type=TYPE_MODULE,
            relation_type=USES_VAR,
            to_entity=var_name,
            to_type=TYPE_SCSS_VARIABLE,
            source_file=file_path,
            line_number=line,
        ))

    # For SCSS files, index @import / @use / @forward as IMPORTS edges so --deps works.
    if is_scss:
        for match in _SCSS_IMPORT_RE.finditer(source_text):
            imported = match.group(1)
            line = source_text[: match.start()].count("\n") + 1
            triples.append(CodeTriple(
                from_entity=module_name,
                from_type=TYPE_MODULE,
                relation_type=IMPORTS,
                to_entity=imported,
                to_type=TYPE_MODULE,
                source_file=file_path,
                line_number=line,
            ))

    return triples


# ---------------------------------------------------------------------------
# Lit CSS template literal extraction (.styles.ts)
# ---------------------------------------------------------------------------

def _extract_lit_css_tokens(source_text: str, file_path: str) -> list[CodeTriple]:
    """Extract USES_VAR and DEFINED_IN triples from Lit css`...` template literals.

    Finds every css`...` block in the source, strips ${...} interpolations so
    dynamic expressions don't cause false positives or crashes, then scans the
    remaining CSS text with the same regexes used for plain CSS/SCSS files.

    Called as a secondary pass on top of the normal TS extraction — existing
    CALLS/IMPORTS/INHERITS triples are unaffected.
    """
    module_name = _module_name_from_path(file_path)
    file_name = Path(file_path).name
    triples: list[CodeTriple] = []
    seen_uses: set[str] = set()
    seen_defs: set[str] = set()

    for block_match in _LIT_CSS_TEMPLATE_RE.finditer(source_text):
        block_content = block_match.group(1)
        block_start = block_match.start(1)

        # Strip ${...} interpolations — leave surrounding CSS text intact.
        css_text = _TEMPLATE_EXPR_RE.sub("", block_content)

        # var(--foo) usages → USES_VAR (one triple per unique variable per file)
        for m in _CSS_VAR_RE.finditer(css_text):
            var_name = m.group(1)
            if var_name in seen_uses:
                continue
            seen_uses.add(var_name)
            abs_pos = block_start + m.start()
            line = source_text[:abs_pos].count("\n") + 1
            triples.append(CodeTriple(
                from_entity=module_name,
                from_type=TYPE_MODULE,
                relation_type=USES_VAR,
                to_entity=var_name,
                to_type=TYPE_SCSS_VARIABLE,
                source_file=file_path,
                line_number=line,
            ))

        # --foo: value declarations → DEFINED_IN (one triple per unique prop per file)
        for m in _CSS_CUSTOM_PROP_RE.finditer(css_text):
            prop_name = m.group(1)
            if prop_name in seen_defs:
                continue
            seen_defs.add(prop_name)
            abs_pos = block_start + m.start()
            line = source_text[:abs_pos].count("\n") + 1
            triples.append(CodeTriple(
                from_entity=prop_name,
                from_type=TYPE_SCSS_VARIABLE,
                relation_type=DEFINED_IN,
                to_entity=file_name,
                to_type=TYPE_FILE,
                source_file=file_path,
                line_number=line,
            ))

    return triples


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_EXTRACTORS: dict[str, Callable] = {
    ".py":   _extract_python,
    ".js":   _extract_javascript,
    ".jsx":  _extract_javascript,
    ".ts":   _extract_javascript,
    ".tsx":  _extract_javascript,
    ".html": _extract_html,
    ".css":  _extract_css,
    ".scss": _extract_css,
    ".php":  _extract_php,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_file(file_path: str, project_root: str) -> list[CodeTriple]:
    """Parse a single source file into CodeTriples.

    Returns an empty list if the extension is unsupported or parsing fails.
    Never raises — a single bad file does not abort full-repo ingestion.
    """
    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return []

    loader = _PARSER_LOADERS.get(ext)
    extractor = _EXTRACTORS.get(ext)
    if loader is None or extractor is None:
        return []

    try:
        parser, _lang = loader()
        source = Path(file_path).read_bytes()
        tree = parser.parse(source)
        relative_path = os.path.relpath(file_path, project_root)
        triples = extractor(tree.root_node, source, relative_path)

        # Secondary pass: extract CSS tokens from Lit css`...` template literals.
        # Applies to any .styles.ts file — these are invisible to the TS extractor
        # because css`...` content is opaque to tree-sitter's TypeScript grammar.
        if relative_path.endswith(".styles.ts"):
            triples += _extract_lit_css_tokens(
                source.decode("utf-8", errors="replace"), relative_path
            )

        return triples
    except Exception as exc:
        print(f"[code_parser] skipping {file_path}: {exc}")
        return []


def parse_directory(
    project_root: str,
    skip_dirs: set[str] | None = None,
    progress: bool = False,
) -> list[CodeTriple]:
    """Recursively parse all supported files under project_root.

    Args:
        project_root: Absolute path to the repo root.
        skip_dirs: Directory names to skip (merged with defaults).
        progress: Show a tqdm progress bar while parsing.
    """
    default_skip = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".mypy_cache", ".pytest_cache",
        "coverage", "tmp", "cache", ".nx", "lcov-report",
    }
    ignored = (skip_dirs or set()) | default_skip

    # Collect all files first so tqdm can show a total
    source_files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in ignored]
        for filename in filenames:
            if Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS:
                source_files.append(os.path.join(dirpath, filename))

    if progress:
        try:
            from tqdm import tqdm
            source_files_iter = tqdm(source_files, desc="Parsing files", unit="file")
        except ImportError:
            source_files_iter = source_files
    else:
        source_files_iter = source_files

    triples: list[CodeTriple] = []
    for full_path in source_files_iter:
        triples.extend(parse_file(full_path, project_root))

    return triples


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_meaningful_callee(name: str) -> bool:
    """Return True if name is worth recording as a CALLS target."""
    return (
        name not in _NOISE_CALLEES
        and len(name) > 1
        and not name.startswith("__")
    )


def _module_name_from_path(file_path: str) -> str:
    """Convert a relative file path to a dotted module name.

    'src/auth/login.py' → 'src.auth.login'
    """
    without_ext = os.path.splitext(file_path)[0]
    return without_ext.replace(os.sep, ".").replace("/", ".")
