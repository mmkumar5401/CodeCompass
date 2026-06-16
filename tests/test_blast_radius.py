"""Tests for --blast-radius — BUF-5 acceptance criteria.

Uses unittest.mock to avoid a live Neo4j dependency. Integration tests
that need a real graph are marked with @pytest.mark.integration.
"""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph.code_query_cli import run_blast_radius


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(rows, target_file, updated_at=None):
    """Return a mock CodeGraphClient pre-configured for get_blast_radius."""
    client = MagicMock()
    client.get_blast_radius.return_value = (rows, target_file)
    client.get_file_updated_at.return_value = updated_at
    return client


def _run(target, rows, target_file, capsys, *, hops=3, rich=False, updated_at=None):
    client = _make_client(rows, target_file, updated_at)
    with patch("graph.code_query_cli.get_client", return_value=client):
        run_blast_radius(target, "test_project", max_hops=hops, rich=rich)
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# Happy path — symbol target
# ---------------------------------------------------------------------------

def test_symbol_target_lists_reachable_files(capsys):
    rows = [
        {"file": "a/b.py", "edge_type": "CALLS", "hops": 1},
        {"file": "a/c.py", "edge_type": "IMPORTS", "hops": 2},
    ]
    out = _run("my_function", rows, "src/main.py", capsys)
    assert "src/main.py" in out   # target file at hop 0
    assert "a/b.py" in out
    assert "a/c.py" in out


def test_symbol_target_summary_line(capsys):
    rows = [
        {"file": "a/b.py", "edge_type": "CALLS", "hops": 1},
        {"file": "a/c.py", "edge_type": "IMPORTS", "hops": 2},
    ]
    out = _run("my_function", rows, "src/main.py", capsys)
    # 3 files (target + 2 deps), across 2 hops
    assert "# blast radius: 3 files across 2 hops" in out


def test_output_is_one_file_per_line(capsys):
    rows = [
        {"file": "x/a.py", "edge_type": "CALLS", "hops": 1},
        {"file": "x/b.py", "edge_type": "CALLS", "hops": 1},
    ]
    out = _run("func", rows, "src/entry.py", capsys)
    lines = [l for l in out.strip().splitlines() if not l.startswith("#")]
    # Each non-summary line should be a bare file path
    for line in lines:
        assert " " not in line.strip(), f"Expected bare path, got: {line!r}"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_duplicate_rows_deduped_to_minimum_hop(capsys):
    rows = [
        {"file": "shared.py", "edge_type": "CALLS", "hops": 2},
        {"file": "shared.py", "edge_type": "IMPORTS", "hops": 1},
    ]
    out = _run("func", rows, "src/main.py", capsys)
    file_lines = [l for l in out.splitlines() if "shared.py" in l]
    assert len(file_lines) == 1, "shared.py should appear exactly once"


def test_target_file_included_exactly_once_even_if_in_rows(capsys):
    rows = [
        {"file": "src/main.py", "edge_type": "CALLS", "hops": 1},
        {"file": "other.py", "edge_type": "CALLS", "hops": 1},
    ]
    out = _run("func", rows, "src/main.py", capsys)
    count = out.count("src/main.py")
    assert count == 1


# ---------------------------------------------------------------------------
# Hop limit
# ---------------------------------------------------------------------------

def test_hop_limit_respected(capsys):
    # Client is expected to honour max_hops; verify the right value is passed.
    rows = [{"file": "direct.py", "edge_type": "CALLS", "hops": 1}]
    client = _make_client(rows, "src/main.py")
    with patch("graph.code_query_cli.get_client", return_value=client):
        run_blast_radius("func", "test_project", max_hops=1)
    client.get_blast_radius.assert_called_once_with("func", "test_project", 1)


# ---------------------------------------------------------------------------
# Not found → ERROR + non-zero exit
# ---------------------------------------------------------------------------

def test_not_found_exits_nonzero():
    client = _make_client([], None)
    with patch("graph.code_query_cli.get_client", return_value=client):
        with pytest.raises(SystemExit) as exc_info:
            run_blast_radius("nonexistent_fn", "test_project")
    assert exc_info.value.code != 0


def test_not_found_prints_error(capsys):
    client = _make_client([], None)
    with patch("graph.code_query_cli.get_client", return_value=client):
        with pytest.raises(SystemExit):
            run_blast_radius("nonexistent_fn", "test_project")
    out = capsys.readouterr().out
    assert "ERROR:" in out
    assert "nonexistent_fn" in out
    assert "test_project" in out


# ---------------------------------------------------------------------------
# Empty graph — target found but no outbound edges
# ---------------------------------------------------------------------------

def test_empty_graph_no_traceback(capsys):
    # target_file is known but it has no outbound edges → rows is empty
    out = _run("lone_func", [], "solo.py", capsys)
    assert "solo.py" in out
    assert "# blast radius: 1 files across 0 hops" in out


# ---------------------------------------------------------------------------
# Rich output
# ---------------------------------------------------------------------------

def test_rich_output_contains_headers(capsys):
    rows = [{"file": "a.py", "edge_type": "CALLS", "hops": 1}]
    out = _run("func", rows, "src/main.py", capsys, rich=True)
    assert "File" in out
    assert "Relationship" in out
    assert "Hops" in out


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotency(capsys):
    rows = [
        {"file": "a/b.py", "edge_type": "CALLS", "hops": 1},
        {"file": "a/c.py", "edge_type": "IMPORTS", "hops": 2},
    ]
    out1 = _run("func", rows, "src/main.py", capsys)
    out2 = _run("func", rows, "src/main.py", capsys)
    assert out1 == out2


# ---------------------------------------------------------------------------
# Staleness stamp
# ---------------------------------------------------------------------------

def test_staleness_stamp_included(capsys):
    rows = [{"file": "a.py", "edge_type": "CALLS", "hops": 1}]
    out = _run("func", rows, "src/main.py", capsys, updated_at="2026-01-01T00:00:00+00:00")
    assert "# index updated:" in out
