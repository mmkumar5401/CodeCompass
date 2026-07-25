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

    async def handler(msg):
        # msg.data is {"msg": "...", "extra": None} when sent via ctx.log
        text = msg.data.get("msg", "") if isinstance(msg.data, dict) else str(msg.data or "")
        seen.append(text)

    async with Client(mcp_server.mcp, log_handler=handler) as client:
        result = await client.call_tool("ingest", {})

    assert result.data["status"] == "ok"
    assert len(seen) >= 3  # at least hierarchy, parsing, done
    # Every message carries a bracketed percent: [2%], [5%], …, [100%]
    import re
    pct_re = re.compile(r"^\[(\d+)%\]")
    percents = [int(m.group(1)) for t in seen if (m := pct_re.match(t))]
    assert percents  # at least one bracketed percent
    assert percents == sorted(percents)  # monotonic
    assert percents[0] < 100 and percents[-1] == 100
    assert any("Parsing" in t for t in seen)


@pytest.fixture
def anyio_backend():
    return "asyncio"
