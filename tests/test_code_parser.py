"""Tests for CSS/SCSS/HTML ingestion — BUF-16 acceptance criteria."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.code_parser import parse_file


def _parse(content: str, suffix: str) -> list:
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        return parse_file(path, os.path.dirname(path))
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# CSS variable declarations
# ---------------------------------------------------------------------------

def test_css_variable_declaration_indexed():
    triples = _parse(":root { --my-var: red; }", ".css")
    rel_types = {t.relation_type for t in triples}
    assert "DEFINED_IN" in rel_types
    names = {t.from_entity for t in triples if t.relation_type == "DEFINED_IN"}
    assert "--my-var" in names


# ---------------------------------------------------------------------------
# CSS variable usages → USES_VAR
# ---------------------------------------------------------------------------

def test_css_variable_usage_indexed():
    triples = _parse("a { color: var(--my-var); }", ".css")
    uses = [t for t in triples if t.relation_type == "USES_VAR"]
    assert uses, "Expected at least one USES_VAR triple"
    assert uses[0].to_entity == "--my-var"


def test_css_variable_usage_dedup():
    src = "a { color: var(--x); } b { background: var(--x); }"
    triples = _parse(src, ".css")
    uses = [t for t in triples if t.relation_type == "USES_VAR" and t.to_entity == "--x"]
    assert len(uses) == 1, "Duplicate USES_VAR triples should be collapsed per file"


def test_scss_nested_variable_usage():
    src = ".parent { .child { color: var(--nested-var); } }"
    triples = _parse(src, ".scss")
    uses = [t for t in triples if t.relation_type == "USES_VAR"]
    assert any(t.to_entity == "--nested-var" for t in uses)


# ---------------------------------------------------------------------------
# SCSS @import / @use → IMPORTS
# ---------------------------------------------------------------------------

def test_scss_import_indexed():
    src = '@import "variables";\n.a { color: red; }'
    triples = _parse(src, ".scss")
    imports = [t for t in triples if t.relation_type == "IMPORTS"]
    assert imports, "Expected IMPORTS triple from @import"
    assert imports[0].to_entity == "variables"


def test_scss_use_indexed():
    src = '@use "sass:color";\n.a { color: red; }'
    triples = _parse(src, ".scss")
    imports = [t for t in triples if t.relation_type == "IMPORTS"]
    assert any(t.to_entity == "sass:color" for t in imports)


# ---------------------------------------------------------------------------
# HTML custom element tag references → REFERENCES
# ---------------------------------------------------------------------------

def test_html_custom_element_tag_indexed():
    triples = _parse('<a-button color="blue">click</a-button>', ".html")
    refs = [t for t in triples if t.relation_type == "REFERENCES"]
    assert refs, "Expected REFERENCES triple for custom element"
    assert refs[0].to_entity == "a-button"


def test_html_custom_element_dedup():
    src = "<a-button></a-button><a-button></a-button>"
    triples = _parse(src, ".html")
    refs = [t for t in triples if t.relation_type == "REFERENCES" and t.to_entity == "a-button"]
    assert len(refs) == 1, "Duplicate REFERENCES triples should be collapsed per file"


def test_html_plain_tags_not_indexed_as_references():
    triples = _parse('<div class="foo"><p>hello</p></div>', ".html")
    refs = [t for t in triples if t.relation_type == "REFERENCES"]
    assert not refs, "Plain HTML tags without a hyphen should not produce REFERENCES triples"


# ---------------------------------------------------------------------------
# No regression on existing JS/TS ingestion
# ---------------------------------------------------------------------------

def test_existing_js_behaviour_unchanged():
    src = 'import { foo } from "./bar";\nfoo();'
    triples = _parse(src, ".js")
    rel_types = {t.relation_type for t in triples}
    assert "IMPORTS" in rel_types
    assert "CALLS" in rel_types


def test_css_does_not_emit_js_relations():
    triples = _parse(":root { --color: blue; }", ".css")
    rel_types = {t.relation_type for t in triples}
    assert "CALLS" not in rel_types
    assert "INHERITS" not in rel_types
