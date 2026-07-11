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

    exported = _collect_python_exports(root)
    type_env = _py_type_env(root)
    class_parents = _py_class_parents(root)

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
                        is_exported=name in exported,
                        owner_class=_enclosing_python_class(node),
                    ))

            case "class_definition":
                name = _get_node_name(node, ["identifier"])
                if not name:
                    continue
                class_name = name

                triples.append(CodeTriple(
                    from_entity=class_name,
                    from_type=TYPE_CLASS,
                    relation_type=DEFINED_IN,
                    to_entity=module_name,
                    to_type=TYPE_MODULE,
                    source_file=file_path,
                    line_number=_line(node),
                    is_exported=class_name in exported,
                ))

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
                callee, receiver, obj = _extract_python_call_parts(node)
                if callee and _is_meaningful_callee(callee):
                    scope = _enclosing_scope(node)
                    caller = scope or module_name
                    caller_type = TYPE_FUNCTION if scope else TYPE_MODULE
                    receiver_type = _resolve_py_receiver_type(receiver, obj, node, type_env, class_parents)
                    triples.append(CodeTriple(
                        from_entity=caller,
                        from_type=caller_type,
                        relation_type=CALLS,
                        to_entity=callee,
                        to_type=TYPE_FUNCTION,
                        source_file=file_path,
                        line_number=_line(node),
                        call_receiver=receiver,
                        call_receiver_type=receiver_type,
                        owner_class=_enclosing_python_class(node) if scope else None,
                    ))

    return triples


def _extract_python_callee(call_node: Node) -> str | None:
    """Back-compat shim: callee name only."""
    return _extract_python_call_parts(call_node)[0]


def _extract_python_call_parts(call_node: Node) -> tuple[str | None, str | None, Node | None]:
    """Return (callee_name, receiver_text, receiver_object_node) for a `call`."""
    if not call_node.children:
        return None, None, None
    fn_node = call_node.children[0]
    if fn_node.type == "identifier":
        return _text(fn_node), None, None
    if fn_node.type == "attribute":
        # `obj.method` — the called attribute is the LAST identifier, the object
        # it is accessed on is the receiver (e.g. pipeline.submit → "submit"
        # called on "pipeline").
        attr = fn_node.child_by_field_name("attribute")
        obj = fn_node.child_by_field_name("object")
        if attr is None:
            idents = [c for c in fn_node.children if c.type == "identifier"]
            attr = idents[-1] if idents else None
        receiver = _text(obj) if obj is not None else None
        return (_text(attr) if attr else None), receiver, obj
    return None, None, None


def _py_call_class(node: Node | None) -> str | None:
    """Class name if `node` is an instantiation `Foo(...)`.

    Heuristic: the callee is a bare identifier that is either CapWorded (the
    PEP 8 class convention) or a dotted attribute ending in one. Returns None
    for lower-case function calls.
    """
    if node is None or node.type != "call":
        return None
    fn = node.children[0] if node.children else None
    if fn is None:
        return None
    if fn.type == "identifier":
        name = _text(fn)
    elif fn.type == "attribute":
        attr = fn.child_by_field_name("attribute")
        name = _text(attr) if attr is not None else ""
    else:
        return None
    return name if name and name[:1].isupper() else None


def _py_type_name(ann: Node | None) -> str | None:
    """First plain type name from a Python annotation node.

    `Foo` -> "Foo"; `list[Foo]` -> "list" (skipped as builtin); unions/optionals
    resolve to their first identifier. Lower-case builtins are ignored.
    """
    if ann is None:
        return None
    for desc in _walk(ann):
        if desc.type == "identifier":
            name = _text(desc)
            if name and name[:1].isupper():
                return name
    return None


def _py_return_types(root: Node) -> dict[str, str]:
    """Map function name -> its declared return type (`def f(...) -> Foo:`).

    Enables return-type inference: `x = self.get_adapter(url)` gets typed by
    `get_adapter`'s `-> BaseAdapter` annotation. Same-named functions with
    conflicting return types are dropped (can't disambiguate statically)."""
    rets: dict[str, str] = {}
    conflict: set[str] = set()
    for node in _walk(root):
        if node.type == "function_definition":
            name = _get_node_name(node, ["identifier"])
            rt = node.child_by_field_name("return_type")
            t = _py_type_name(rt) if rt is not None else None
            if name and t:
                if name in rets and rets[name] != t:
                    conflict.add(name)
                else:
                    rets[name] = t
    for name in conflict:
        rets.pop(name, None)
    return rets


def _py_type_env(root: Node) -> dict[str, str]:
    """Best-effort variable → class map for a Python module.

    Binds from unambiguous local signals: `x = Foo()` instantiations, type
    annotations (`x: Foo`, `def f(x: Foo)`), and return-type inference
    (`x = get_thing()` where `get_thing` is declared `-> Foo`). A name bound to
    two different types is dropped rather than mis-resolved.
    """
    ret_types = _py_return_types(root)
    types: dict[str, str] = {}
    ambiguous: set[str] = set()

    def bind(name: str | None, t: str | None) -> None:
        if not name or not t:
            return
        if name in types and types[name] != t:
            ambiguous.add(name)
        else:
            types[name] = t

    for node in _walk(root):
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            ann = node.child_by_field_name("type")
            right = node.child_by_field_name("right")
            if left is not None and left.type == "identifier":
                name = _text(left)
                bind(name, _py_type_name(ann))
                if ann is None:
                    bind(name, _py_call_class(right))
                    # return-type inference: x = fn(...) / x = obj.fn(...)
                    if right is not None and right.type == "call":
                        callee = _extract_python_call_parts(right)[0]
                        if callee:
                            bind(name, ret_types.get(callee))
        elif node.type in ("typed_parameter", "typed_default_parameter"):
            ident = _child_of_type(node, "identifier")
            ann = node.child_by_field_name("type")
            bind(_text(ident) if ident is not None else None, _py_type_name(ann))

    for name in ambiguous:
        types.pop(name, None)
    return types


def _py_class_parents(root: Node) -> dict[str, str]:
    """Map class name -> its first base class, for resolving `super()`."""
    parents: dict[str, str] = {}
    for node in _walk(root):
        if node.type == "class_definition":
            name = _get_node_name(node, ["identifier"])
            arg = _child_of_type(node, "argument_list")
            if name and arg:
                bases = [c for c in arg.children if c.type == "identifier"]
                if bases:
                    parents[name] = _text(bases[0])
    return parents


def _enclosing_python_class(node: Node) -> str | None:
    """Name of the nearest enclosing `class C:`, for resolving `self`/`cls`."""
    current = node.parent
    while current:
        if current.type == "class_definition":
            name_node = _child_of_type(current, "identifier")
            if name_node:
                return _text(name_node)
        current = current.parent
    return None


def _resolve_py_receiver_type(receiver: str | None, obj: Node | None, call_node: Node,
                              env: dict[str, str], parents: dict[str, str] | None = None) -> str | None:
    """Infer a Python receiver's type from `self`/`cls`, `super()`, inline `Foo()`, or env."""
    if _py_call_class(obj) is not None:
        return _py_call_class(obj)
    if receiver in ("self", "cls"):
        return _enclosing_python_class(call_node)
    if receiver in ("super()", "super") and parents:
        return parents.get(_enclosing_python_class(call_node))
    if receiver is not None and receiver in env:
        return env[receiver]
    return None


def _collect_python_exports(root: Node) -> set[str]:
    """Names that are public API of a Python module.

    Python has no `module.exports`; public surface is conventional. A symbol is
    treated as public API when it is any of:
      - listed in a module-level `__all__`,
      - a public (non-underscore) function — module-level or a class method
        (instance methods dispatch dynamically and rarely have a captured
        static caller), or
      - a public (non-underscore) class.

    Public symbols may be called only by external consumers, so lacking an
    in-repo caller is not evidence of dead code — they are surfaced as possible
    entry points instead. Underscore-private symbols remain genuine candidates.
    """
    exported: set[str] = set()

    for node in _walk(root):
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is not None and _text(left) == "__all__" and right is not None:
                for desc in _walk(right):
                    if desc.type == "string":
                        content = _child_of_type(desc, "string_content")
                        name = _text(content) if content is not None else _text(desc).strip("'\"")
                        if name:
                            exported.add(name)
        elif node.type in ("function_definition", "class_definition"):
            name_node = _child_of_type(node, "identifier")
            if name_node is not None:
                name = _text(name_node)
                if not name.startswith("_"):
                    exported.add(name)

    return exported


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


def _php_type_basename(node: Node | None) -> str | None:
    """Class name from a PHP type node (`named_type`/`type`/`qualified_name`),
    stripping any namespace. Skips scalar/pseudo types (int, string, void, …)."""
    if node is None:
        return None
    for desc in _walk(node):
        if desc.type in ("name", "qualified_name"):
            base = _php_basename(desc)
            if base and base[:1].isupper():  # PSR class-name convention
                return base
    return None


def _php_new_type(node: Node | None) -> str | None:
    """Class name of `new X(...)`, else None."""
    if node is None or node.type != "object_creation_expression":
        return None
    for child in node.children:
        if child.type in ("name", "qualified_name"):
            base = _php_basename(child)
            if base and base.lower() not in _PHP_SELF_REFERENTIAL:
                return base
    return None


def _php_is_public(method_node: Node) -> bool:
    """PHP method visibility — public (or no modifier, which defaults public) is
    API; private/protected is internal. Reads the `visibility_modifier` child."""
    for child in method_node.children:
        if child.type == "visibility_modifier":
            return _text(child).lower() not in ("private", "protected")
    return True  # PHP methods default to public


def _php_return_types(root: Node) -> dict[str, str]:
    """Map function/method name -> declared return type (`function f(): Foo`)."""
    rets: dict[str, str] = {}
    conflict: set[str] = set()
    for node in _walk(root):
        if node.type in ("function_definition", "method_declaration"):
            name = _php_name(node)
            rt = node.child_by_field_name("return_type")
            t = _php_type_basename(rt) if rt is not None else None
            if name and t:
                if name in rets and rets[name] != t:
                    conflict.add(name)
                else:
                    rets[name] = t
    for name in conflict:
        rets.pop(name, None)
    return rets


def _php_type_env(root: Node) -> dict[str, str]:
    """Best-effort PHP variable → class map (no `$` in keys).

    Binds from `$x = new Foo()`, typed params (`function f(Foo $x)`), and
    return-type inference (`$x = make()` where `make(): Foo`). Conflicts dropped.
    """
    ret_types = _php_return_types(root)
    types: dict[str, str] = {}
    ambiguous: set[str] = set()

    def bind(name: str | None, t: str | None) -> None:
        if not name or not t:
            return
        if name in types and types[name] != t:
            ambiguous.add(name)
        else:
            types[name] = t

    for node in _walk(root):
        if node.type == "assignment_expression" and node.children:
            lhs = node.children[0]
            rhs = node.children[-1]
            if lhs.type == "variable_name":
                name = _php_var_name(lhs)
                bind(name, _php_new_type(rhs))
                if rhs.type in ("function_call_expression", "member_call_expression",
                                "nullsafe_member_call_expression", "scoped_call_expression"):
                    callee = _child_of_type(rhs, "name")
                    if callee is not None:
                        bind(name, ret_types.get(_text(callee)))
        elif node.type == "simple_parameter":
            var = _child_of_type(node, "variable_name")
            ty = node.child_by_field_name("type")
            if var is not None and ty is not None:
                bind(_php_var_name(var), _php_type_basename(ty))

    for name in ambiguous:
        types.pop(name, None)
    return types


def _php_class_parents(root: Node) -> dict[str, str]:
    """Map class name -> its parent (`extends`), for resolving `parent::`."""
    parents: dict[str, str] = {}
    for node in _walk(root):
        if node.type == "class_declaration":
            name = _php_name(node)
            base = _child_of_type(node, "base_clause")
            if name and base:
                targets = _php_extends_targets(base)
                if targets:
                    parents[name] = _php_basename(targets[0])
    return parents


def _php_call_receiver(node: Node, env: dict[str, str]) -> tuple[str | None, str | None]:
    """Receiver text + inferred type for a member call `$obj->method()`."""
    obj = node.child_by_field_name("object")
    if obj is None:
        obj = node.children[0] if node.children else None
    if obj is None:
        return None, None
    # inline `(new Foo())->m()`
    nt = _php_new_type(obj)
    if nt:
        return "new", nt
    if obj.type == "variable_name":
        var = _php_var_name(obj)
        if var == "this":
            container = _enclosing_php_container(node)
            return "this", (container[0] if container else None)
        return var, env.get(var)
    return _text(obj), None


def _extract_php(root: Node, source: bytes, file_path: str) -> list[CodeTriple]:
    module_name = _module_name_from_path(file_path)
    triples: list[CodeTriple] = []
    type_env = _php_type_env(root)
    class_parents = _php_class_parents(root)

    def defined_in(name: str, entity_type: str, line: int, is_exported: bool = True,
                   owner: str | None = None) -> None:
        triples.append(CodeTriple(
            from_entity=name,
            from_type=entity_type,
            relation_type=DEFINED_IN,
            to_entity=module_name,
            to_type=TYPE_MODULE,
            source_file=file_path,
            line_number=line,
            is_exported=is_exported,
            owner_class=owner,
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

    def calls(callee: str, callee_type: str, line: int, scope_node: Node,
              receiver: str | None = None, receiver_type: str | None = None) -> None:
        if not callee or not _is_meaningful_callee(callee):
            return
        scope = _enclosing_php_scope(scope_node)
        caller, caller_type = scope if scope else (module_name, TYPE_MODULE)
        container = _enclosing_php_container(scope_node)
        triples.append(CodeTriple(
            from_entity=caller,
            from_type=caller_type,
            relation_type=CALLS,
            to_entity=callee,
            to_type=callee_type,
            source_file=file_path,
            line_number=line,
            call_receiver=receiver,
            call_receiver_type=receiver_type,
            owner_class=container[0] if (scope and container) else None,
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
                    container = _enclosing_php_container(node)
                    defined_in(name, TYPE_FUNCTION, _line(node), is_exported=_php_is_public(node),
                               owner=container[0] if container else None)

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
                    recv, recv_type = _php_call_receiver(node, type_env)
                    calls(_text(callee_node), TYPE_FUNCTION, _line(node), node,
                          receiver=recv, receiver_type=recv_type)

            case "scoped_call_expression":
                names = _children_of_type(node, "name")
                if names:
                    method = _text(names[-1])
                    scope_node = node.children[0] if node.children else None
                    scope_text = _text(scope_node) if scope_node is not None else ""
                    if scope_text == "parent":
                        container = _enclosing_php_container(node)
                        rtype = class_parents.get(container[0]) if container else None
                    elif scope_text in ("self", "static"):
                        container = _enclosing_php_container(node)
                        rtype = container[0] if container else None
                    else:
                        rtype = _php_basename(scope_node) if scope_node is not None else None
                    calls(method, TYPE_FUNCTION, _line(node), node,
                          receiver=scope_text or None, receiver_type=rtype)

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

    # Pre-scan for names that reach the module's public API so definitions can
    # be tagged is_exported (used by dead-code analysis to avoid false positives).
    exported = _collect_js_exports(root)

    # Best-effort variable → type map for receiver type inference on calls.
    type_env = _js_type_env(root)
    class_parents = _js_class_parents(root)

    def defined(name: str, line: int, owner: str | None = None) -> None:
        triples.append(CodeTriple(
            from_entity=name,
            from_type=TYPE_FUNCTION,
            relation_type=DEFINED_IN,
            to_entity=module_name,
            to_type=TYPE_MODULE,
            source_file=file_path,
            line_number=line,
            is_exported=name in exported,
            owner_class=owner,
        ))

    for node in _walk(root):
        match node.type:
            case "function_declaration" | "function_expression":
                name_node = _child_of_type(node, "identifier")
                if name_node:
                    defined(_text(name_node), _line(name_node))

            case "method_definition":
                name_node = _child_of_type(node, "property_identifier")
                if name_node:
                    defined(_text(name_node), _line(name_node), owner=_enclosing_class_name(node))

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
                        defined(_text(name_node), _line(name_node))

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
                # CommonJS require('x') / dynamic import('x') → IMPORTS edge,
                # so require-based codebases get the same import graph as ESM.
                import_target = _extract_js_require_target(node)
                if import_target is not None:
                    triples.append(CodeTriple(
                        from_entity=module_name,
                        from_type=TYPE_MODULE,
                        relation_type=IMPORTS,
                        to_entity=import_target,
                        to_type=TYPE_MODULE,
                        source_file=file_path,
                        line_number=_line(node),
                    ))
                    continue

                callee, receiver, obj = _extract_js_call_parts(node)
                if callee and _is_meaningful_callee(callee):
                    scope = _enclosing_js_scope(node)
                    caller = scope or module_name
                    caller_type = TYPE_FUNCTION if scope else TYPE_MODULE
                    receiver_type = _resolve_receiver_type(receiver, obj, node, type_env, class_parents)
                    triples.append(CodeTriple(
                        from_entity=caller,
                        from_type=caller_type,
                        relation_type=CALLS,
                        to_entity=callee,
                        to_type=TYPE_FUNCTION,
                        source_file=file_path,
                        line_number=_line(node),
                        call_receiver=receiver,
                        call_receiver_type=receiver_type,
                        owner_class=_enclosing_class_name(node) if scope else None,
                    ))

    return triples


def _collect_js_exports(root: Node) -> set[str]:
    """Names that reach the module's public API.

    Recognizes three CommonJS/ESM patterns:
      - `export function foo` / `export const foo` / `export { foo }`
      - `module.exports = foo` / `exports.bar = foo` (RHS identifier is public)
      - property assignments onto the exports object: if `module.exports = res`,
        then every `res.method = ...` marks `method` public. Two passes handle
        methods attached before the final `module.exports =` line.
    """
    exported: set[str] = set()
    export_objects: set[str] = {"exports"}  # `exports.x = ...` is always public

    # Pass 1: ES exports + discover the exports-object alias(es).
    for node in _walk(root):
        if node.type == "export_statement":
            for ident in _walk(node):
                if ident.type == "identifier" and ident.parent is not None and \
                        ident.parent.type not in ("member_expression",):
                    # declaration name or `export { name }` specifier
                    exported.add(_text(ident))
        elif node.type == "assignment_expression":
            left, right = _assignment_sides(node)
            if left is None:
                continue
            left_text = _text(left)
            # module.exports = <ident>  →  <ident> is the exports object + public
            if left_text in ("module.exports", "exports") and right is not None:
                if right.type == "identifier":
                    name = _text(right)
                    exported.add(name)
                    export_objects.add(name)
        elif node.type == "variable_declarator":
            # `var app = exports = module.exports = {}` — the declared name is an
            # alias of the exports object, so its properties are public too.
            name_node = _child_of_type(node, "identifier")
            value = node.child_by_field_name("value")
            if name_node is not None and value is not None and \
                    value.type == "assignment_expression" and \
                    "module.exports" in _text(value):
                export_objects.add(_text(name_node))

    # Pass 2: property assignments and defineGetter/defineProperty registrations
    # onto any exports object → the property is public.
    for node in _walk(root):
        if node.type == "assignment_expression":
            left, right = _assignment_sides(node)
            if left is None or left.type != "member_expression":
                continue
            obj = left.child_by_field_name("object")
            prop = left.child_by_field_name("property")
            if obj is None or prop is None:
                continue
            if _text(obj) in export_objects:
                exported.add(_text(prop))
                if right is not None and right.type == "identifier":
                    exported.add(_text(right))
        elif node.type == "call_expression":
            # defineGetter(obj, 'name', fn) / Object.defineProperty(obj, 'name', …)
            # register a property on an exports object — treat 'name' as public.
            exported |= _defined_property_exports(node, export_objects)

    return exported


def _defined_property_exports(call_node: Node, export_objects: set[str]) -> set[str]:
    """Property names registered on an exports object via a define* helper.

    Matches the common getter/property registration idiom
    (`defineGetter(req, 'hostname', fn)`, `Object.defineProperty(res, 'x', …)`):
    a define-style callee, a first argument that is a known exports object, and
    a string-literal property name.
    """
    callee = _extract_js_call(call_node)[0] or ""
    if "define" not in callee.lower():
        return set()
    args = _child_of_type(call_node, "arguments")
    if args is None:
        return set()
    arg_nodes = [c for c in args.children if c.type not in (",", "(", ")")]
    if not arg_nodes or _text(arg_nodes[0]) not in export_objects:
        return set()
    for a in arg_nodes[1:]:
        if a.type == "string":
            frag = _child_of_type(a, "string_fragment")
            return {_text(frag) if frag else _text(a).strip("'\"`")}
    return set()


def _assignment_sides(node: Node) -> tuple[Node | None, Node | None]:
    """Left and right operand of an assignment_expression, via named fields with
    a positional fallback (grammar versions differ on field availability)."""
    left = node.child_by_field_name("left")
    right = node.child_by_field_name("right")
    if left is None or right is None:
        named = [c for c in node.children if c.type != "="]
        if len(named) >= 2:
            left = left or named[0]
            right = right or named[-1]
    return left, right


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


def _extract_js_call(call_node: Node) -> tuple[str | None, str | None]:
    """Return (callee_name, receiver_text) for a call_expression.

    `foo()`      -> ("foo", None)
    `app.handle()` -> ("handle", "app")
    `this.router.handle()` -> ("handle", "this.router")
    """
    callee, receiver, _obj = _extract_js_call_parts(call_node)
    return callee, receiver


def _extract_js_call_parts(call_node: Node) -> tuple[str | None, str | None, Node | None]:
    """Like _extract_js_call, but also returns the receiver's object node so the
    caller can inspect it for type inference (e.g. an inline `new Foo()`)."""
    if not call_node.children:
        return None, None, None
    fn_node = call_node.children[0]
    if fn_node.type == "identifier":
        return _text(fn_node), None, None
    if fn_node.type == "member_expression":
        prop = _child_of_type(fn_node, "property_identifier")
        obj = fn_node.child_by_field_name("object")
        receiver = _text(obj) if obj is not None else None
        return (_text(prop) if prop else None), receiver, obj
    return None, None, None


def _new_expression_type(node: Node | None) -> str | None:
    """Constructor name of a `new Foo(...)` expression, else None."""
    if node is None or node.type != "new_expression":
        return None
    ctor = node.child_by_field_name("constructor")
    if ctor is None:
        ctor = _child_of_type(node, "identifier")
    return _text(ctor) if ctor is not None else None


def _type_from_annotation(ann: Node | None) -> str | None:
    """Simple type name from a TypeScript `type_annotation` node.

    Returns the identifier for plain named types (`Foo`, `Router`); skips
    unions, generics, and built-ins that carry no useful disambiguation.
    """
    if ann is None:
        return None
    for desc in _walk(ann):
        if desc.type in ("type_identifier",):
            name = _text(desc)
            if name and name not in ("any", "unknown", "void", "never"):
                return name
    return None


def _js_type_env(root: Node) -> dict[str, str]:
    """Best-effort variable → type map for a file.

    Binds from unambiguous, local signals:
      - `var x = new Foo()`            -> x : Foo
      - TS annotations `let x: Foo`,
        `function f(x: Foo)`           -> x : Foo
      - return-type inference `const x = getThing()` where TS declares
        `function getThing(): Foo`    -> x : Foo

    A name bound to two different types anywhere in the file is dropped as
    ambiguous — better to fall back to name-based handling than to mis-resolve.
    """
    ret_types = _js_return_types(root)
    types: dict[str, str] = {}
    ambiguous: set[str] = set()

    def bind(name: str | None, t: str | None) -> None:
        if not name or not t:
            return
        if name in types and types[name] != t:
            ambiguous.add(name)
        else:
            types[name] = t

    for node in _walk(root):
        if node.type == "variable_declarator":
            name_node = _child_of_type(node, "identifier")
            name = _text(name_node) if name_node else None
            value = node.child_by_field_name("value")
            bind(name, _new_expression_type(value))
            bind(name, _type_from_annotation(_child_of_type(node, "type_annotation")))
            # return-type inference: const x = fn(...) / const x = obj.fn(...)
            if value is not None and value.type == "call_expression":
                callee = _extract_js_call(value)[0]
                if callee:
                    bind(name, ret_types.get(callee))
        elif node.type in ("required_parameter", "optional_parameter"):
            pat = node.child_by_field_name("pattern") or _child_of_type(node, "identifier")
            ann = _child_of_type(node, "type_annotation")
            bind(_text(pat) if pat is not None else None, _type_from_annotation(ann))

    for name in ambiguous:
        types.pop(name, None)
    return types


def _js_return_types(root: Node) -> dict[str, str]:
    """Map function name -> its TS return type (`function f(): Foo` / `f(): Foo`).

    Same-named functions with conflicting return types are dropped."""
    rets: dict[str, str] = {}
    conflict: set[str] = set()
    for node in _walk(root):
        if node.type in ("function_declaration", "function_expression", "method_definition"):
            name_node = (_child_of_type(node, "identifier")
                         or _child_of_type(node, "property_identifier"))
            rt = node.child_by_field_name("return_type")
            t = _type_from_annotation(rt) if rt is not None else None
            if name_node is not None and t:
                name = _text(name_node)
                if name in rets and rets[name] != t:
                    conflict.add(name)
                else:
                    rets[name] = t
    for name in conflict:
        rets.pop(name, None)
    return rets


def _enclosing_class_name(node: Node) -> str | None:
    """Name of the nearest enclosing `class C { ... }`, for resolving `this`."""
    current = node.parent
    while current:
        if current.type in ("class_declaration", "class"):
            name_node = _child_of_type(current, "type_identifier") or \
                _child_of_type(current, "identifier")
            if name_node:
                return _text(name_node)
        current = current.parent
    return None


def _js_class_parents(root: Node) -> dict[str, str]:
    """Map class name -> the class it `extends`, for resolving `super`."""
    parents: dict[str, str] = {}
    for node in _walk(root):
        if node.type in ("class_declaration", "class"):
            name_node = _child_of_type(node, "type_identifier") or _child_of_type(node, "identifier")
            heritage = _child_of_type(node, "class_heritage")
            if name_node is not None and heritage is not None:
                base = None
                for desc in _walk(heritage):
                    if desc.type in ("identifier", "type_identifier"):
                        base = _text(desc)
                        break
                if base:
                    parents[_text(name_node)] = base
    return parents


def _resolve_receiver_type(receiver: str | None, obj: Node | None, call_node: Node,
                           env: dict[str, str], parents: dict[str, str] | None = None) -> str | None:
    """Infer the receiver's type from an inline `new`, `this`, `super`, or the type env."""
    if _new_expression_type(obj) is not None:
        return _new_expression_type(obj)
    if receiver in ("this",):
        return _enclosing_class_name(call_node)
    if receiver == "super" and parents:
        return parents.get(_enclosing_class_name(call_node))
    if receiver is not None and receiver in env:
        return env[receiver]
    return None


def _extract_js_callee(call_node: Node) -> str | None:
    """Back-compat shim: callee name only."""
    return _extract_js_call(call_node)[0]


def _extract_js_require_target(call_node: Node) -> str | None:
    """Module string of a `require('x')` or dynamic `import('x')` call, else None.

    Only the single static string-literal argument form is recognized; dynamic
    paths (`require(base + name)`) have no static target and are skipped.
    """
    if not call_node.children:
        return None
    fn_node = call_node.children[0]
    is_require = fn_node.type == "identifier" and _text(fn_node) == "require"
    is_dynamic_import = fn_node.type == "import"
    if not (is_require or is_dynamic_import):
        return None

    args = _child_of_type(call_node, "arguments")
    if args is None:
        return None
    str_node = _child_of_type(args, "string")
    if str_node is None:
        return None
    frag = _child_of_type(str_node, "string_fragment")
    return _text(frag) if frag else _text(str_node).strip("'\"`")


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
