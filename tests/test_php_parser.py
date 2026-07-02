"""Tests for PHP ingestion entity coverage."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.code_parser import parse_file


def _parse(content: str) -> list:
    with tempfile.NamedTemporaryFile(suffix=".php", mode="w", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        return parse_file(path, os.path.dirname(path))
    finally:
        os.unlink(path)


def _rels(triples, relation_type=None, from_type=None, to_type=None):
    out = triples
    if relation_type is not None:
        out = [t for t in out if t.relation_type == relation_type]
    if from_type is not None:
        out = [t for t in out if t.from_type == from_type]
    if to_type is not None:
        out = [t for t in out if t.to_type == to_type]
    return out


# ---------------------------------------------------------------------------
# The parser must actually run — regression guard for the broken loader
# (tsphp.language vs tsphp.language_php) that silently no-op'd every .php file.
# ---------------------------------------------------------------------------

def test_php_file_parses_without_error():
    triples = _parse("<?php\nfunction foo() { return 1; }\n")
    assert triples, "PHP parsing should produce triples, not silently fail"


# ---------------------------------------------------------------------------
# Functions, classes, inheritance
# ---------------------------------------------------------------------------

def test_top_level_function_indexed():
    triples = _parse("<?php\nfunction topLevel($x) { return $x; }\n")
    defs = _rels(triples, relation_type="DEFINED_IN", from_type="function")
    assert any(t.from_entity == "topLevel" for t in defs)


def test_class_extends_indexed():
    triples = _parse("<?php\nclass Foo extends Bar {}\n")
    inh = _rels(triples, relation_type="INHERITS", to_type="class")
    assert any(t.from_entity == "Foo" and t.to_entity == "Bar" for t in inh)


def test_class_implements_indexed():
    triples = _parse("<?php\nclass Foo implements A, B {}\n")
    inh = _rels(triples, relation_type="INHERITS", to_type="interface")
    targets = {t.to_entity for t in inh}
    assert {"A", "B"} <= targets


# ---------------------------------------------------------------------------
# Methods, properties, constructor promotion, constants
# ---------------------------------------------------------------------------

def test_class_method_indexed():
    src = "<?php\nclass Foo {\n    public function bar() { return 1; }\n}\n"
    triples = _parse(src)
    defs = _rels(triples, relation_type="DEFINED_IN", from_type="function")
    assert any(t.from_entity == "bar" for t in defs)


def test_property_declaration_indexed():
    src = "<?php\nclass Foo {\n    protected static ?string $name = \"x\";\n}\n"
    triples = _parse(src)
    props = _rels(triples, relation_type="DEFINED_IN", from_type="property")
    assert any(t.from_entity == "name" and t.to_entity == "Foo" for t in props)


def test_constructor_promoted_property_indexed():
    src = "<?php\nclass Foo {\n    public function __construct(private readonly int $id) {}\n}\n"
    triples = _parse(src)
    props = _rels(triples, relation_type="DEFINED_IN", from_type="property")
    assert any(t.from_entity == "id" and t.to_entity == "Foo" for t in props)


def test_class_constant_indexed():
    src = "<?php\nclass Foo {\n    public const MAX = 10;\n}\n"
    triples = _parse(src)
    consts = _rels(triples, relation_type="DEFINED_IN", from_type="constant")
    assert any(t.from_entity == "MAX" and t.to_entity == "Foo" for t in consts)


def test_top_level_constant_indexed():
    triples = _parse("<?php\nconst MAX = 10;\n")
    consts = _rels(triples, relation_type="DEFINED_IN", from_type="constant")
    assert any(t.from_entity == "MAX" and t.to_type == "module" for t in consts)


# ---------------------------------------------------------------------------
# Interfaces, traits, enums
# ---------------------------------------------------------------------------

def test_interface_declaration_indexed():
    triples = _parse("<?php\ninterface Payable {\n    public function pay(): void;\n}\n")
    defs = _rels(triples, relation_type="DEFINED_IN", from_type="interface")
    assert any(t.from_entity == "Payable" for t in defs)


def test_interface_extends_multiple_indexed():
    triples = _parse("<?php\ninterface Multi extends X, Y {}\n")
    inh = _rels(triples, relation_type="INHERITS", from_type="interface", to_type="interface")
    targets = {t.to_entity for t in inh}
    assert {"X", "Y"} <= targets


def test_trait_declaration_and_use_indexed():
    src = "<?php\ntrait Loggable {\n    public function log() {}\n}\nclass Foo {\n    use Loggable;\n}\n"
    triples = _parse(src)
    trait_defs = _rels(triples, relation_type="DEFINED_IN", from_type="trait")
    assert any(t.from_entity == "Loggable" for t in trait_defs)
    uses = _rels(triples, relation_type="INHERITS", to_type="trait")
    assert any(t.from_entity == "Foo" and t.to_entity == "Loggable" for t in uses)


def test_enum_and_case_indexed():
    src = "<?php\nenum Status: string {\n    case Active = 'active';\n}\n"
    triples = _parse(src)
    enum_defs = _rels(triples, relation_type="DEFINED_IN", from_type="enum")
    assert any(t.from_entity == "Status" for t in enum_defs)
    cases = _rels(triples, relation_type="DEFINED_IN", from_type="constant", to_type="enum")
    assert any(t.from_entity == "Active" and t.to_entity == "Status" for t in cases)


# ---------------------------------------------------------------------------
# Namespaces / imports / includes
# ---------------------------------------------------------------------------

def test_namespace_use_indexed():
    triples = _parse("<?php\nuse App\\Contracts\\Payable;\n")
    imports = _rels(triples, relation_type="IMPORTS")
    assert any(t.to_entity == "App.Contracts.Payable" for t in imports)


def test_namespace_use_group_indexed():
    triples = _parse("<?php\nuse App\\{Bar, Baz};\n")
    imports = _rels(triples, relation_type="IMPORTS")
    targets = {t.to_entity for t in imports}
    assert {"App.Bar", "App.Baz"} <= targets


def test_require_once_indexed():
    triples = _parse("<?php\nrequire_once 'bootstrap.php';\n")
    includes = _rels(triples, relation_type="INCLUDES")
    assert any(t.to_entity == "bootstrap.php" for t in includes)


# ---------------------------------------------------------------------------
# Calls: plain, method, static, new, closures
# ---------------------------------------------------------------------------

def test_plain_function_call_indexed():
    triples = _parse("<?php\nfunction outer() { inner(); }\nfunction inner() {}\n")
    calls = _rels(triples, relation_type="CALLS")
    assert any(t.from_entity == "outer" and t.to_entity == "inner" for t in calls)


def test_method_call_indexed():
    src = "<?php\nfunction run() {\n    $obj = new Foo();\n    $obj->save();\n}\n"
    triples = _parse(src)
    calls = _rels(triples, relation_type="CALLS")
    assert any(t.to_entity == "save" and t.to_type == "function" for t in calls)
    assert any(t.to_entity == "Foo" and t.to_type == "class" for t in calls)


def test_static_call_indexed():
    src = "<?php\nfunction run() {\n    BaseModel::make();\n}\n"
    triples = _parse(src)
    calls = _rels(triples, relation_type="CALLS")
    assert any(t.to_entity == "make" for t in calls)


def test_self_new_not_recorded_as_class_entity():
    src = "<?php\nclass Foo {\n    public static function make() {\n        return new static();\n    }\n}\n"
    triples = _parse(src)
    calls = _rels(triples, relation_type="CALLS", to_type="class")
    assert not any(t.to_entity.lower() in ("self", "static", "parent") for t in calls)


def test_closure_assigned_to_variable_indexed():
    src = "<?php\nfunction run() {\n    $fn = function($x) { return $x; };\n}\n"
    triples = _parse(src)
    defs = _rels(triples, relation_type="DEFINED_IN", from_type="function")
    assert any(t.from_entity == "fn" for t in defs)


def test_arrow_function_assigned_to_variable_indexed():
    src = "<?php\nfunction run() {\n    $arrow = fn($x) => $x + 1;\n}\n"
    triples = _parse(src)
    defs = _rels(triples, relation_type="DEFINED_IN", from_type="function")
    assert any(t.from_entity == "arrow" for t in defs)


# ---------------------------------------------------------------------------
# No regression on other extractors
# ---------------------------------------------------------------------------

def test_php_does_not_emit_html_relations():
    triples = _parse("<?php\nclass Foo {}\n")
    rel_types = {t.relation_type for t in triples}
    assert "HAS_CLASS" not in rel_types
    assert "STYLES" not in rel_types
