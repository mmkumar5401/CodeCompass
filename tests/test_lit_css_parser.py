"""Tests for Lit css`...` template literal extraction — BUF-22 acceptance criteria."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.code_parser import parse_file, _extract_lit_css_tokens


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_styles_ts(content: str) -> list:
    """Write content to a temp .styles.ts file and parse it."""
    with tempfile.NamedTemporaryFile(suffix=".styles.ts", mode="w", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        return parse_file(path, os.path.dirname(path))
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Basic var() usage → USES_VAR
# ---------------------------------------------------------------------------

def test_var_usage_in_template_literal():
    src = "const styles = css`color: var(--my-token);`;"
    triples = _parse_styles_ts(src)
    uses = [t for t in triples if t.relation_type == "USES_VAR"]
    assert uses, "Expected at least one USES_VAR triple"
    assert any(t.to_entity == "--my-token" for t in uses)


def test_multiple_var_usages_all_indexed():
    src = "const s = css`color: var(--color-a); background: var(--color-b);`;"
    triples = _parse_styles_ts(src)
    uses = {t.to_entity for t in triples if t.relation_type == "USES_VAR"}
    assert "--color-a" in uses
    assert "--color-b" in uses


def test_var_usage_deduplicated_per_file():
    src = "const s = css`color: var(--x); border: var(--x);`;"
    triples = _parse_styles_ts(src)
    uses = [t for t in triples if t.relation_type == "USES_VAR" and t.to_entity == "--x"]
    assert len(uses) == 1, "Duplicate USES_VAR should be collapsed"


# ---------------------------------------------------------------------------
# CSS custom property declaration → DEFINED_IN
# ---------------------------------------------------------------------------

def test_custom_prop_declaration_indexed():
    src = "const s = css`:host { --my-token: red; }`;"
    triples = _parse_styles_ts(src)
    defs = [t for t in triples if t.relation_type == "DEFINED_IN"]
    assert any(t.from_entity == "--my-token" for t in defs)


def test_custom_prop_declaration_deduplicated():
    src = "const s = css`:host { --tok: 1; --tok: 2; }`;"
    triples = _parse_styles_ts(src)
    defs = [t for t in triples if t.relation_type == "DEFINED_IN" and t.from_entity == "--tok"]
    assert len(defs) == 1


# ---------------------------------------------------------------------------
# Multiple css`...` blocks
# ---------------------------------------------------------------------------

def test_multiple_css_blocks_all_parsed():
    src = (
        "styles.push(css`color: var(--token-a);`);\n"
        "styles.push(css`background: var(--token-b);`);\n"
    )
    triples = _parse_styles_ts(src)
    uses = {t.to_entity for t in triples if t.relation_type == "USES_VAR"}
    assert "--token-a" in uses
    assert "--token-b" in uses


# ---------------------------------------------------------------------------
# Dynamic expressions stripped — no crash
# ---------------------------------------------------------------------------

def test_dynamic_expression_does_not_crash():
    src = "const s = css`color: ${color('blue', 600)};`;"
    # Should not raise
    triples = _parse_styles_ts(src)
    # No false USES_VAR from the expression
    assert not any(t.to_entity == "color" for t in triples if t.relation_type == "USES_VAR")


def test_dynamic_expression_surrounding_css_still_parsed():
    src = "const s = css`color: ${color('blue')}; background: var(--bg);`;"
    triples = _parse_styles_ts(src)
    uses = {t.to_entity for t in triples if t.relation_type == "USES_VAR"}
    assert "--bg" in uses


# ---------------------------------------------------------------------------
# No TS regression — IMPORTS and CALLS still present
# ---------------------------------------------------------------------------

def test_ts_imports_still_extracted():
    src = (
        'import { css } from "lit";\n'
        "const s = css`color: var(--tok);`;\n"
    )
    triples = _parse_styles_ts(src)
    rel_types = {t.relation_type for t in triples}
    assert "IMPORTS" in rel_types, "IMPORTS triples must still be present"
    assert "USES_VAR" in rel_types, "USES_VAR triples must also be present"


def test_ts_calls_still_extracted():
    src = (
        "import { css } from 'lit';\n"
        "function render() { return css`color: var(--x);`; }\n"
    )
    triples = _parse_styles_ts(src)
    # render should appear as a DEFINED_IN (function) triple
    func_triples = [t for t in triples if t.from_entity == "render"]
    assert func_triples, "Function definition triples must still be extracted"


# ---------------------------------------------------------------------------
# Non-.styles.ts files are unaffected
# ---------------------------------------------------------------------------

def test_plain_ts_file_no_lit_extraction():
    src = "const s = css`color: var(--tok);`;"
    with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        triples = parse_file(path, os.path.dirname(path))
    finally:
        os.unlink(path)
    # A plain .ts file should NOT get USES_VAR triples (no secondary pass)
    uses = [t for t in triples if t.relation_type == "USES_VAR"]
    assert not uses, "Plain .ts files must not trigger Lit CSS extraction"


# ---------------------------------------------------------------------------
# _extract_lit_css_tokens unit tests (direct)
# ---------------------------------------------------------------------------

def test_extract_returns_empty_for_no_template_literals():
    result = _extract_lit_css_tokens("const x = 1;", "button.styles.ts")
    assert result == []


def test_extract_handles_empty_template_literal():
    result = _extract_lit_css_tokens("const s = css``;", "button.styles.ts")
    assert result == []


def test_extract_line_numbers_are_positive():
    src = "const s = css`\n  color: var(--tok);\n`;"
    result = _extract_lit_css_tokens(src, "button.styles.ts")
    for t in result:
        assert t.line_number >= 1
