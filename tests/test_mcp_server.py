"""Tests for the CodeCompass MCP server."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mcp_server as server_module


@pytest.fixture
def repo_path():
    """Use the codecompass repo itself, which already has a graph."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def configured(repo_path):
    """Configure the module-level repo for a test and restore it after."""
    original = server_module._REPO_PATH
    server_module._REPO_PATH = repo_path
    try:
        yield
    finally:
        server_module._REPO_PATH = original


@pytest.mark.asyncio
async def test_set_repo_configures_state_and_returns_ok(repo_path):
    server_module._REPO_PATH = None
    result = await server_module.mcp.call_tool("set_repo", {"repo_path": repo_path})
    assert not result.is_error
    assert repo_path in result.content[0].text
    assert server_module._REPO_PATH == repo_path


@pytest.mark.asyncio
async def test_get_repo_when_not_configured():
    server_module._REPO_PATH = None
    result = await server_module.mcp.call_tool("get_repo", {})
    assert not result.is_error
    assert "No repository configured" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_tools_registered(configured):
    tools = await server_module.mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "set_repo",
        "get_repo",
        "init",
        "ingest",
        "add_entity",
        "add_call",
        "blast_radius",
        "batch_impact",
        "impact",
        "deps",
        "trace",
        "styles",
        "flow",
        "dead_code",
        "tree",
    }
    assert expected <= names, f"Missing tools: {expected - names}"


@pytest.mark.asyncio
async def test_tree_tool_returns_structure(configured):
    result = await server_module.mcp.call_tool("tree", {})
    assert not result.is_error
    text = result.content[0].text
    assert "Project tree" in text or "codecompass" in text


@pytest.mark.asyncio
async def test_impact_tool_for_known_symbol(configured):
    result = await server_module.mcp.call_tool("impact", {"symbol": "main"})
    assert not result.is_error
    text = result.content[0].text
    assert "main" in text


@pytest.mark.asyncio
async def test_flow_tool_returns_lean_structure(configured):
    # flow is lean now: structure only, no embedded source/content field.
    result = await server_module.mcp.call_tool("flow", {"entry_symbol": "main"})
    assert not result.is_error
    text = result.content[0].text
    assert "entry_point" in text
    assert "content" not in text  # narration/source lives in flow_summary, not flow


@pytest.mark.asyncio
async def test_flow_summary_tool_returns_content(configured):
    result = await server_module.mcp.call_tool(
        "flow_summary", {"entry_symbol": "main", "format": "mermaid"}
    )
    assert not result.is_error
    assert "entry_point" in result.content[0].text


@pytest.mark.asyncio
async def test_query_tool_fails_without_repo():
    server_module._REPO_PATH = None
    with pytest.raises(Exception) as exc_info:
        await server_module.mcp.call_tool("tree", {})
    assert "set_repo" in str(exc_info.value)
