"""The MCP ingest tool streams progress notifications while it works."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.anyio
async def test_ingest_reports_progress(tmp_path, monkeypatch):
    from fastmcp import Client

    import mcp_server

    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    for i in range(5):
        (repo / "pkg" / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")

    monkeypatch.setattr(mcp_server, "_REPO_PATH", str(repo))
    seen = []

    async def handler(progress: float, total: float | None, message: str | None):
        seen.append((progress, total, message))

    async with Client(mcp_server.mcp, progress_handler=handler) as client:
        result = await client.call_tool("ingest", {})

    assert result.data["status"] == "ok"
    percents = [p for p, _, _ in seen]
    assert percents == sorted(percents)  # monotonic
    assert percents[0] < 100 and percents[-1] == 100
    assert all(t == 100 for _, t, _ in seen)
    assert any("Parsing" in (m or "") for _, _, m in seen)


@pytest.fixture
def anyio_backend():
    return "asyncio"
