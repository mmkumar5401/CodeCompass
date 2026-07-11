"""Accuracy fixes for impact / blast_radius / dead_code.

Covers three benchmark-surfaced bugs:
  1. CommonJS `require()` was not recorded as an import (blast_radius miss).
  2. Same-named methods on different receivers merged silently (impact FP).
  3. Exported public API flagged as dead code (dead_code FP).
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.code_parser import parse_file
from graph.code_graph_client import LocalGraphClient
from models.code_types import CodeTriple


def _parse(content: str, suffix: str = ".js") -> list[CodeTriple]:
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        return parse_file(path, os.path.dirname(path))
    finally:
        os.unlink(path)


def _client() -> LocalGraphClient:
    tmp = tempfile.mkdtemp()
    return LocalGraphClient(os.path.join(tmp, ".codecompass", "graph.json"))


def _write(client: LocalGraphClient, triples: list[CodeTriple], project="proj") -> None:
    file_ids = {t.source_file for t in triples}
    for fid in file_ids:
        node_id = f"{project}:file:{fid}"
        client.graph.add_node(node_id, type="File", path=fid, project=project)
    id_map = {fid: f"{project}:file:{fid}" for fid in file_ids}
    client.write_code_triples_batch(triples, id_map, project)


# ---------------------------------------------------------------------------
# Fix 1 — require() → IMPORTS
# ---------------------------------------------------------------------------

def test_require_call_recorded_as_import():
    triples = _parse("var res = require('./response');")
    imports = [t for t in triples if t.relation_type == "IMPORTS"]
    assert imports, "require('./response') should emit an IMPORTS triple"
    assert imports[0].to_entity == "./response"


def test_require_does_not_emit_calls_to_require():
    triples = _parse("var x = require('./foo');")
    calls = [t for t in triples if t.relation_type == "CALLS" and t.to_entity == "require"]
    assert not calls, "require itself must not be recorded as a CALLS target"


def test_dynamic_import_recorded_as_import():
    triples = _parse("async function f(){ const m = await import('./lazy'); }")
    imports = [t for t in triples if t.relation_type == "IMPORTS"]
    assert any(t.to_entity == "./lazy" for t in imports)


def test_dynamic_require_path_skipped():
    triples = _parse("var m = require('./views/' + name);")
    imports = [t for t in triples if t.relation_type == "IMPORTS"]
    assert not imports, "non-literal require paths have no static target"


def test_blast_radius_includes_relative_importer():
    # express.js requires ./response; editing response.js should surface express.js
    triples = [
        CodeTriple("lib.express", "module", "IMPORTS", "./response", "module", "lib/express.js", 1),
        CodeTriple("send", "function", "DEFINED_IN", "lib.response", "module", "lib/response.js", 5),
    ]
    client = _client()
    _write(client, triples)
    rows, target_file = client.get_blast_radius("lib/response.js", "proj")
    files = {r["file"] for r in rows}
    assert "lib/express.js" in files, "direct importer must appear in blast radius"


def test_blast_radius_ignores_package_import():
    triples = [
        CodeTriple("lib.express", "module", "IMPORTS", "router", "module", "lib/express.js", 1),
        CodeTriple("send", "function", "DEFINED_IN", "lib.response", "module", "lib/response.js", 5),
    ]
    client = _client()
    _write(client, triples)
    rows, _ = client.get_blast_radius("lib/response.js", "proj")
    files = {r["file"] for r in rows}
    assert "lib/express.js" not in files, "unrelated package import must not match"


# ---------------------------------------------------------------------------
# Fix 2 — receiver capture + disambiguation
# ---------------------------------------------------------------------------

def test_member_call_captures_receiver():
    triples = _parse("function f(){ app.handle(a, b); }")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver == "app"


def test_bare_call_has_no_receiver():
    triples = _parse("function f(){ handle(a); }")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver is None


def test_impact_filters_by_receiver():
    # Two callers of a method named "handle" on different receivers.
    triples = [
        CodeTriple("appCaller", "function", "CALLS", "handle", "function", "lib/express.js", 3,
                   call_receiver="app"),
        CodeTriple("routerCaller", "function", "CALLS", "handle", "function", "test/Router.js", 8,
                   call_receiver="router"),
    ]
    client = _client()
    _write(client, triples)

    all_callers = {r["caller_name"] for r in client.find_callers("handle", "proj")}
    assert all_callers == {"appCaller", "routerCaller"}, "unqualified query returns both"

    app_only = {r["caller_name"] for r in client.find_callers("app.handle", "proj")}
    assert app_only == {"appCaller"}, "qualified query filters to the app receiver"

    router_only = {r["caller_name"] for r in client.find_callers("router.handle", "proj")}
    assert router_only == {"routerCaller"}


def test_impact_rows_carry_receiver():
    triples = [
        CodeTriple("c", "function", "CALLS", "handle", "function", "a.js", 1, call_receiver="app"),
    ]
    client = _client()
    _write(client, triples)
    rows = client.find_callers("handle", "proj")
    assert rows[0]["receiver"] == "app"


def test_this_receiver_matches_qualified_query():
    triples = [
        CodeTriple("c", "function", "CALLS", "handle", "function", "a.js", 1, call_receiver="this"),
    ]
    client = _client()
    _write(client, triples)
    assert client.find_callers("app.handle", "proj"), "this.* should match a qualified query"


# ---------------------------------------------------------------------------
# Fix 3 — export awareness in dead-code
# ---------------------------------------------------------------------------

def test_module_exports_object_methods_marked_exported():
    src = (
        "var res = {};\n"
        "res.send = function send(body){ return body; };\n"
        "res.json = function json(obj){ return obj; };\n"
        "module.exports = res;\n"
    )
    triples = _parse(src)
    exported = {t.from_entity for t in triples if t.relation_type == "DEFINED_IN" and t.is_exported}
    assert "send" in exported
    assert "json" in exported


def test_es_export_function_marked_exported():
    triples = _parse("export function publicFn(){ return 1; }")
    exported = {t.from_entity for t in triples if t.relation_type == "DEFINED_IN" and t.is_exported}
    assert "publicFn" in exported


def test_private_helper_not_marked_exported():
    src = (
        "var res = {};\n"
        "res.send = function send(){ return helper(); };\n"
        "function helper(){ return 1; }\n"
        "module.exports = res;\n"
    )
    triples = _parse(src)
    by_name = {t.from_entity: t.is_exported for t in triples if t.relation_type == "DEFINED_IN"}
    assert by_name.get("send") is True
    assert by_name.get("helper") is False


# ---------------------------------------------------------------------------
# Fix 2b — receiver TYPE inference (auto-disambiguation)
# ---------------------------------------------------------------------------

def test_new_expression_receiver_type_inferred():
    triples = _parse("function f(){ var r = new Router(); r.handle(x); }")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver_type == "Router"


def test_inline_new_receiver_type_inferred():
    triples = _parse("function f(){ new Router().handle(x); }")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver_type == "Router"


def test_typescript_annotation_receiver_type_inferred():
    triples = _parse("function f(r: Router){ r.handle(x); }", suffix=".ts")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver_type == "Router"


def test_this_receiver_type_is_enclosing_class():
    src = "class Dog { bark(){ this.wag(); } }"
    triples = _parse(src, suffix=".ts")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "wag")
    assert call.call_receiver_type == "Dog"


def test_ambiguous_variable_type_dropped():
    src = "function f(){ var x = new Dog(); x.bark(); } function g(){ var x = new Cat(); x.bark(); }"
    triples = _parse(src)
    types = {t.call_receiver_type for t in triples if t.to_entity == "bark"}
    # `x` binds to two types across the file → ambiguous → no type asserted
    assert types == {None}


def test_impact_auto_disambiguates_by_type():
    # Two classes expose bark(); calls are typed via `new`. impact("Dog.bark")
    # must return only the Dog caller, with no shared receiver *name*.
    triples = [
        CodeTriple("a", "function", "CALLS", "bark", "function", "a.js", 1,
                   call_receiver="d", call_receiver_type="Dog"),
        CodeTriple("b", "function", "CALLS", "bark", "function", "b.js", 1,
                   call_receiver="t", call_receiver_type="Tree"),
    ]
    client = _client()
    _write(client, triples)

    assert {r["caller_name"] for r in client.find_callers("bark", "proj")} == {"a", "b"}
    assert {r["caller_name"] for r in client.find_callers("Dog.bark", "proj")} == {"a"}
    assert {r["caller_name"] for r in client.find_callers("Tree.bark", "proj")} == {"b"}


def test_impact_type_beats_coincidental_name():
    # A caller whose receiver is *named* "Router" but *typed* Duck must not
    # satisfy a Router-typed query — type wins over a name collision.
    triples = [
        CodeTriple("real", "function", "CALLS", "quack", "function", "a.js", 1,
                   call_receiver="r", call_receiver_type="Router"),
        CodeTriple("fake", "function", "CALLS", "quack", "function", "b.js", 1,
                   call_receiver="Router", call_receiver_type="Duck"),
    ]
    client = _client()
    _write(client, triples)
    assert {r["caller_name"] for r in client.find_callers("Router.quack", "proj")} == {"real"}


def test_impact_rows_carry_receiver_type():
    triples = [
        CodeTriple("c", "function", "CALLS", "handle", "function", "a.js", 1,
                   call_receiver="r", call_receiver_type="Router"),
    ]
    client = _client()
    _write(client, triples)
    assert client.find_callers("handle", "proj")[0]["receiver_type"] == "Router"


def test_dead_code_excludes_exported_symbol():
    triples = [
        # exported public API, no in-repo caller
        CodeTriple("send", "function", "DEFINED_IN", "lib.response", "module", "lib/response.js", 5,
                   is_exported=True),
        # genuinely dead private helper, no caller
        CodeTriple("orphan", "function", "DEFINED_IN", "lib.response", "module", "lib/response.js", 9),
    ]
    client = _client()
    _write(client, triples)
    result = client.find_dead_code("proj")
    dead_names = {e["name"] for e in result["dead"]}
    maybe_names = {e["name"] for e in result["maybe_entrypoint"]}
    assert "orphan" in dead_names, "true dead code still reported"
    assert "send" not in dead_names, "exported symbol must not be called dead"
    assert "send" in maybe_names, "exported symbol surfaces as a possible entry point"


# ---------------------------------------------------------------------------
# Cross-language: the same fixes apply to the Python extractor
# ---------------------------------------------------------------------------

def _parse_py(content: str) -> list[CodeTriple]:
    return _parse(content, suffix=".py")


def test_python_member_call_captures_receiver():
    triples = _parse_py("def f():\n    app.handle(x)\n")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver == "app"


def test_python_instantiation_type_inferred():
    triples = _parse_py("def f():\n    r = Router()\n    r.handle(x)\n")
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver_type == "Router"


def test_python_self_receiver_type_is_class():
    src = "class Dog:\n    def bark(self):\n        self.wag()\n"
    triples = _parse_py(src)
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "wag")
    assert call.call_receiver_type == "Dog"


def test_python_annotation_receiver_type_inferred():
    src = "def f(r: Router):\n    r.handle(x)\n"
    triples = _parse_py(src)
    call = next(t for t in triples if t.relation_type == "CALLS" and t.to_entity == "handle")
    assert call.call_receiver_type == "Router"


def test_python_all_marks_exported():
    # `public_fn` is exported via __all__; `_helper` is underscore-private and
    # stays a genuine candidate (public module-level names are exported too now,
    # so the counterexample must be private).
    src = "__all__ = ['public_fn']\n\ndef public_fn():\n    pass\n\ndef _helper():\n    pass\n"
    triples = _parse_py(src)
    by_name = {t.from_entity: t.is_exported for t in triples if t.relation_type == "DEFINED_IN"}
    assert by_name.get("public_fn") is True
    assert by_name.get("_helper") is False


def test_python_public_method_marked_exported():
    src = "class Flask:\n    def route(self):\n        pass\n    def _private(self):\n        pass\n"
    triples = _parse_py(src)
    by_name = {t.from_entity: t.is_exported for t in triples if t.relation_type == "DEFINED_IN"}
    assert by_name.get("route") is True, "public class method is public API"
    assert by_name.get("_private") is False, "underscore method is not exported"


def test_python_public_module_function_marked_exported():
    src = "def has_app_context():\n    return True\n\ndef _helper():\n    pass\n"
    triples = _parse_py(src)
    by_name = {t.from_entity: t.is_exported for t in triples if t.relation_type == "DEFINED_IN"}
    assert by_name.get("has_app_context") is True, "public module-level function is public API"
    assert by_name.get("_helper") is False


def test_python_public_class_marked_exported():
    src = "class FlaskProxy:\n    pass\n"
    triples = _parse_py(src)
    defs = [t for t in triples if t.relation_type == "DEFINED_IN" and t.from_type == "class"]
    assert defs and defs[0].from_entity == "FlaskProxy"
    assert defs[0].is_exported is True


def test_dunder_methods_are_entry_points_not_dead():
    triples = [
        CodeTriple("__call__", "function", "DEFINED_IN", "flask.app", "module", "src/flask/app.py", 5),
        CodeTriple("_real_orphan", "function", "DEFINED_IN", "flask.app", "module", "src/flask/app.py", 9),
    ]
    client = _client()
    _write(client, triples)
    dc = client.find_dead_code("proj")
    dead = {e["name"] for e in dc["dead"]}
    maybe = {e["name"] for e in dc["maybe_entrypoint"]}
    assert "__call__" not in dead, "runtime-invoked dunder must not be called dead"
    assert "__call__" in maybe
    assert "_real_orphan" in dead, "private orphan is still a real candidate"


def test_python_impact_disambiguates_by_type():
    triples = [
        CodeTriple("a", "function", "CALLS", "bark", "function", "a.py", 2,
                   call_receiver="d", call_receiver_type="Dog"),
        CodeTriple("b", "function", "CALLS", "bark", "function", "b.py", 2,
                   call_receiver="t", call_receiver_type="Tree"),
    ]
    client = _client()
    _write(client, triples)
    assert {r["caller_name"] for r in client.find_callers("Dog.bark", "proj")} == {"a"}
    assert {r["caller_name"] for r in client.find_callers("bark", "proj")} == {"a", "b"}
