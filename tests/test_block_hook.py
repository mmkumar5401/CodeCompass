"""The generated PreToolUse hook blocks grep/cat inside registered codecompass
repos and allows reads outside them."""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main as cc_main


def _write_hook(tmp_path, repo: str):
    script = cc_main._CLAUDE_HOOK_SCRIPT.replace(
        "__CODECOMPASS_REPO__", json.dumps(repo))
    hook = tmp_path / "hook.py"
    hook.write_text(script)
    return hook


def _run(hook, payload, env):
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload), capture_output=True, text=True, env=env)


def test_hook_blocks_inside_repo_allows_outside(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    outside = tmp_path / "notes.txt"
    outside.write_text("hi\n")
    registry = tmp_path / "repos"
    registry.write_text(str(repo) + "\n")
    hook = _write_hook(tmp_path, str(repo))
    env = {**os.environ, "CODECOMPASS_REPOS": str(registry)}

    # cat a file inside the repo -> blocked, points at the MCP tools
    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "cat a.py"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 2 and "codecompass MCP tools" in r.stderr

    # cat a file outside every registered repo -> allowed
    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": f"cat {outside}"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 0

    # git grep inside the repo -> blocked (word match, not just command position)
    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "git grep foo"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 2

    # git cat-file is not a search -> allowed
    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "git cat-file -p HEAD"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 0

    # Grep tool defaulting to cwd (inside the repo) -> blocked
    r = _run(hook, {"tool_name": "Grep",
                    "tool_input": {"pattern": "x"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 2

    # Grep tool pointed outside -> allowed
    r = _run(hook, {"tool_name": "Grep",
                    "tool_input": {"pattern": "x", "path": str(tmp_path)},
                    "cwd": str(repo)}, env)
    assert r.returncode == 0


def test_register_repo_appends_once(tmp_path, monkeypatch):
    registry = tmp_path / "repos"
    monkeypatch.setenv("CODECOMPASS_REPOS", str(registry))
    cc_main._register_repo(str(tmp_path))
    cc_main._register_repo(str(tmp_path))
    assert registry.read_text().splitlines() == [str(tmp_path)]
