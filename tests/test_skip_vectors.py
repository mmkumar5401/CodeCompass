"""Tests for skip_vectors flag in ingest_code and MCP ingest tool."""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main
import mcp_server as server_module


@pytest.fixture
def repo_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def configured(repo_path):
    original = server_module._REPO_PATH
    server_module._REPO_PATH = repo_path
    try:
        yield
    finally:
        server_module._REPO_PATH = original


def _make_mock_client():
    """Create a mock CodeGraphClient with a real temp storage_path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    client = MagicMock()
    client.storage_path = tmp.name
    client.graph = MagicMock()
    client.graph.nodes = MagicMock(return_value=[])
    client.graph.edges = MagicMock(return_value=[])
    client.node_count.return_value = 0
    client.prune_descriptions.return_value = 0
    return client


# --- ingest_code tests ---

def test_ingest_skip_vectors_skips_phase5(repo_path, capsys):
    """skip_vectors=True should skip vector index rebuild entirely."""
    mock_client = _make_mock_client()
    try:
        with patch("main.build_hierarchy", return_value={}), \
             patch("main.get_client", return_value=mock_client), \
             patch("main.get_file_id_map", return_value={}), \
             patch("main.parse_directory", return_value=[MagicMock()]), \
             patch("main._register_project_agents_md"):
            main.ingest_code(repo_path, skip_vectors=True)
        captured = capsys.readouterr()
        assert "Vector index skipped (--skip-vectors)" in captured.out
    finally:
        os.unlink(mock_client.storage_path)


def test_ingest_skip_vectors_false_runs_phase5(repo_path, capsys):
    """skip_vectors=False should attempt Phase 5."""
    mock_client = _make_mock_client()
    try:
        with patch("main.build_hierarchy", return_value={}), \
             patch("main.get_client", return_value=mock_client), \
             patch("main.get_file_id_map", return_value={}), \
             patch("main.parse_directory", return_value=[MagicMock()]), \
             patch("main._register_project_agents_md"), \
             patch("graph.vector_store.index_entities", return_value=42):
            main.ingest_code(repo_path, skip_vectors=False)
        captured = capsys.readouterr()
        assert "Vector index rebuilt" in captured.out
    finally:
        os.unlink(mock_client.storage_path)


def test_ingest_default_skip_vectors_is_true():
    """The function signature should default skip_vectors=True."""
    import inspect
    sig = inspect.signature(main.ingest_code)
    assert sig.parameters["skip_vectors"].default is True


# --- MCP ingest tool tests ---

@pytest.mark.asyncio
async def test_mcp_ingest_default_skip_vectors(configured):
    """MCP ingest tool should default skip_vectors=True."""
    tools = await server_module.mcp.list_tools()
    ingest_tool = next(t for t in tools if t.name == "ingest")
    # FastMCP exposes input schema via .parameters
    props = ingest_tool.parameters.get("properties", {})
    assert "skip_vectors" in props
    assert props["skip_vectors"].get("default") is True


@pytest.mark.asyncio
async def test_mcp_ingest_passes_skip_vectors(configured):
    """MCP ingest should pass skip_vectors through to ingest_code."""
    with patch.object(server_module, "ingest_code") as mock_ingest, \
         patch.object(server_module, "_ensure_initialized"), \
         patch.object(server_module, "_active_repo", return_value="/tmp"):
        await server_module.mcp.call_tool("ingest", {"skip_vectors": False})
        mock_ingest.assert_called_once()
        call_kwargs = mock_ingest.call_args
        assert call_kwargs.kwargs.get("skip_vectors") is False
