"""Tests for --batch-impact — BUF-6 acceptance criteria."""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph.code_query_cli import run_batch_impact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(blast_results: dict):
    """
    blast_results maps target -> (rows, target_file).
    e.g. {"a.py": ([{"file": "dep.py", "edge_type": "CALLS", "hops": 1}], "a.py")}
    """
    client = MagicMock()
    client.get_blast_radius.side_effect = lambda target, project, max_hops: blast_results.get(
        target, ([], None)
    )
    client.get_file_updated_at.return_value = None
    return client


def _run(targets, blast_results, capsys, *, hops=3, rich=False):
    client = _make_client(blast_results)
    with patch("graph.code_query_cli.get_client", return_value=client):
        run_batch_impact(targets, "test_project", max_hops=hops, rich=rich)
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# Single target matches blast-radius output
# ---------------------------------------------------------------------------

def test_single_target_matches_blast_radius(capsys):
    rows = [{"file": "dep.py", "edge_type": "CALLS", "hops": 1}]
    out = _run(["a.py"], {"a.py": (rows, "a.py")}, capsys)
    assert "a.py" in out
    assert "dep.py" in out


def test_single_target_via_annotation(capsys):
    rows = [{"file": "dep.py", "edge_type": "CALLS", "hops": 1}]
    out = _run(["a.py"], {"a.py": (rows, "a.py")}, capsys)
    assert "[via: a.py]" in out


# ---------------------------------------------------------------------------
# Two targets with overlapping dependents — dedup
# ---------------------------------------------------------------------------

def test_overlapping_dependents_deduplicated(capsys):
    shared_row = {"file": "shared.py", "edge_type": "CALLS", "hops": 1}
    blast = {
        "a.py": ([shared_row], "a.py"),
        "b.py": ([shared_row], "b.py"),
    }
    out = _run(["a.py", "b.py"], blast, capsys)
    assert out.count("shared.py") == 1


def test_overlapping_dependents_via_lists_both_targets(capsys):
    shared_row = {"file": "shared.py", "edge_type": "CALLS", "hops": 1}
    blast = {
        "a.py": ([shared_row], "a.py"),
        "b.py": ([shared_row], "b.py"),
    }
    out = _run(["a.py", "b.py"], blast, capsys)
    # The via annotation for shared.py should name both sources
    shared_line = next(l for l in out.splitlines() if "shared.py" in l)
    assert "a.py" in shared_line and "b.py" in shared_line


# ---------------------------------------------------------------------------
# Three targets, no overlap — union is additive
# ---------------------------------------------------------------------------

def test_no_overlap_union_is_additive(capsys):
    blast = {
        "a.py": ([{"file": "dep_a.py", "edge_type": "CALLS", "hops": 1}], "a.py"),
        "b.py": ([{"file": "dep_b.py", "edge_type": "CALLS", "hops": 1}], "b.py"),
        "c.py": ([{"file": "dep_c.py", "edge_type": "CALLS", "hops": 1}], "c.py"),
    }
    out = _run(["a.py", "b.py", "c.py"], blast, capsys)
    for f in ["a.py", "b.py", "c.py", "dep_a.py", "dep_b.py", "dep_c.py"]:
        assert f in out


# ---------------------------------------------------------------------------
# Mixed valid/invalid targets
# ---------------------------------------------------------------------------

def test_mixed_valid_invalid_warns_and_continues(capsys):
    blast = {"valid.py": ([{"file": "dep.py", "edge_type": "CALLS", "hops": 1}], "valid.py")}
    out = _run(["valid.py", "ghost.py"], blast, capsys)
    assert "WARNING" in out
    assert "ghost.py" in out
    assert "dep.py" in out  # valid results still present


def test_mixed_valid_invalid_exits_zero(capsys):
    blast = {"valid.py": ([{"file": "dep.py", "edge_type": "CALLS", "hops": 1}], "valid.py")}
    client = _make_client(blast)
    with patch("graph.code_query_cli.get_client", return_value=client):
        # Should not raise SystemExit
        run_batch_impact(["valid.py", "ghost.py"], "test_project")


# ---------------------------------------------------------------------------
# All invalid → non-zero exit
# ---------------------------------------------------------------------------

def test_all_invalid_exits_nonzero():
    client = _make_client({})
    with patch("graph.code_query_cli.get_client", return_value=client):
        with pytest.raises(SystemExit) as exc_info:
            run_batch_impact(["ghost1.py", "ghost2.py"], "test_project")
    assert exc_info.value.code != 0


def test_all_invalid_prints_warning_per_target(capsys):
    client = _make_client({})
    with patch("graph.code_query_cli.get_client", return_value=client):
        with pytest.raises(SystemExit):
            run_batch_impact(["ghost1.py", "ghost2.py"], "test_project")
    out = capsys.readouterr().out
    assert "ghost1.py" in out
    assert "ghost2.py" in out


# ---------------------------------------------------------------------------
# [also in input] flag
# ---------------------------------------------------------------------------

def test_also_in_input_flag(capsys):
    # b.py is both an input target and a dependent of a.py
    blast = {
        "a.py": ([{"file": "b.py", "edge_type": "CALLS", "hops": 1}], "a.py"),
        "b.py": ([], "b.py"),
    }
    out = _run(["a.py", "b.py"], blast, capsys)
    b_line = next(l for l in out.splitlines() if "b.py" in l and "[via:" in l)
    assert "[also in input]" in b_line


def test_no_also_in_input_for_unrelated_deps(capsys):
    blast = {
        "a.py": ([{"file": "dep.py", "edge_type": "CALLS", "hops": 1}], "a.py"),
    }
    out = _run(["a.py"], blast, capsys)
    dep_line = next(l for l in out.splitlines() if "dep.py" in l)
    assert "[also in input]" not in dep_line


# ---------------------------------------------------------------------------
# --hops is forwarded correctly
# ---------------------------------------------------------------------------

def test_hops_forwarded_to_get_blast_radius():
    blast = {"a.py": ([], "a.py")}
    client = _make_client(blast)
    with patch("graph.code_query_cli.get_client", return_value=client):
        run_batch_impact(["a.py"], "test_project", max_hops=1)
    client.get_blast_radius.assert_called_once_with("a.py", "test_project", 1)


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------

def test_summary_line_format(capsys):
    blast = {
        "a.py": ([{"file": "dep.py", "edge_type": "CALLS", "hops": 1}], "a.py"),
        "b.py": ([{"file": "dep2.py", "edge_type": "CALLS", "hops": 2}], "b.py"),
    }
    out = _run(["a.py", "b.py"], blast, capsys)
    # 4 files total (a.py, b.py, dep.py, dep2.py), 2 input targets, 2 max hops
    assert "# batch impact: 4 files, 2 input targets, 2 hops" in out


# ---------------------------------------------------------------------------
# Rich output
# ---------------------------------------------------------------------------

def test_rich_output_has_table_columns(capsys):
    blast = {"a.py": ([{"file": "dep.py", "edge_type": "CALLS", "hops": 1}], "a.py")}
    out = _run(["a.py"], blast, capsys, rich=True)
    assert "File" in out
    assert "Via" in out
    assert "Hops" in out
