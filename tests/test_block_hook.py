"""The generated PreToolUse hook blocks grep/cat where the graph has an answer
— an indexed file, or a directory holding one — and allows them everywhere else.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main as cc_main


def _write_hook(tmp_path, repo: str):
    script = cc_main._GUARD_HOOK_SCRIPT.replace(
        "__CODECOMPASS_REPO__", json.dumps(repo))
    hook = tmp_path / "hook.py"
    hook.write_text(script)
    return hook


def _write_index(repo, paths):
    """Stand in for the `.codecompass/files.txt` that ingest writes."""
    cc = repo / ".codecompass"
    cc.mkdir(exist_ok=True)
    (cc / "files.txt").write_text("".join(p + "\n" for p in paths))


def _run(hook, payload, env):
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload), capture_output=True, text=True, env=env)


def test_hook_matches_repo_case_insensitively(tmp_path):
    """Hosts pass cwd in whatever case the session started with; on macOS/
    Windows an exact string match would silently allow everything."""
    repo = tmp_path / "Repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    _write_index(repo, ["a.py"])
    registry = tmp_path / "repos"
    registry.write_text(str(repo) + "\n")
    hook = _write_hook(tmp_path, str(repo))
    env = {**os.environ, "CODECOMPASS_REPOS": str(registry)}

    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "cat a.py"},
                    "cwd": str(repo).lower()}, env)
    assert r.returncode == 2


def test_hook_blocks_indexed_allows_outside(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    _write_index(repo, ["a.py"])
    outside = tmp_path / "notes.txt"
    outside.write_text("hi\n")
    registry = tmp_path / "repos"
    registry.write_text(str(repo) + "\n")
    hook = _write_hook(tmp_path, str(repo))
    env = {**os.environ, "CODECOMPASS_REPOS": str(registry)}

    # cat an indexed file -> blocked, points at the MCP tools
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

    # git's other content searches -> blocked
    for cmd in ("git ls-files", "git log -S needle", "git -C . grep foo",
                "git cat-file -p HEAD"):
        r = _run(hook, {"tool_name": "Bash",
                        "tool_input": {"command": cmd},
                        "cwd": str(repo)}, env)
        assert r.returncode == 2, cmd

    # ordinary git history/read commands -> allowed
    for cmd in ("git log --oneline", "git status", "git show HEAD"):
        r = _run(hook, {"tool_name": "Bash",
                        "tool_input": {"command": cmd},
                        "cwd": str(repo)}, env)
        assert r.returncode == 0, cmd

    # Grep tool defaulting to cwd (the repo root, which holds the index) -> blocked
    r = _run(hook, {"tool_name": "Grep",
                    "tool_input": {"pattern": "x"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 2

    # Grep tool pointed outside -> allowed
    r = _run(hook, {"tool_name": "Grep",
                    "tool_input": {"pattern": "x", "path": str(tmp_path)},
                    "cwd": str(repo)}, env)
    assert r.returncode == 0


def test_unindexed_file_inside_repo_is_allowed(tmp_path):
    """Only parsed languages become File nodes. Blocking a yaml the parser
    never read costs a turn and offers no alternative — no graph query
    describes it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / "config.yaml").write_text("k: v\n")
    _write_index(repo, ["a.py"])
    registry = tmp_path / "repos"
    registry.write_text(str(repo) + "\n")
    hook = _write_hook(tmp_path, str(repo))
    env = {**os.environ, "CODECOMPASS_REPOS": str(registry)}

    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "cat config.yaml"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 0

    # the indexed neighbour is still blocked
    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "cat a.py"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 2


def test_directory_scope_follows_the_index(tmp_path):
    """A directory is blocked when it holds an indexed file and allowed when
    it doesn't — `grep -r` asks about a tree, not one path."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n")
    (repo / "docs" / "notes.md").write_text("hi\n")
    _write_index(repo, ["src/a.py"])
    registry = tmp_path / "repos"
    registry.write_text(str(repo) + "\n")
    hook = _write_hook(tmp_path, str(repo))
    env = {**os.environ, "CODECOMPASS_REPOS": str(registry)}

    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "grep -r foo src"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 2

    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "grep -r foo docs"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 0

    # Grep tool pointed at each directory, same verdicts
    r = _run(hook, {"tool_name": "Grep",
                    "tool_input": {"pattern": "x", "path": str(repo / "src")}}, env)
    assert r.returncode == 2
    r = _run(hook, {"tool_name": "Grep",
                    "tool_input": {"pattern": "x", "path": str(repo / "docs")}}, env)
    assert r.returncode == 0


def test_repo_without_an_index_allows_everything(tmp_path):
    """A registered but never-ingested repo has no answers to route to."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    registry = tmp_path / "repos"
    registry.write_text(str(repo) + "\n")
    hook = _write_hook(tmp_path, str(repo))
    env = {**os.environ, "CODECOMPASS_REPOS": str(registry)}

    r = _run(hook, {"tool_name": "Bash",
                    "tool_input": {"command": "cat a.py"},
                    "cwd": str(repo)}, env)
    assert r.returncode == 0


def test_write_file_index_round_trips(tmp_path):
    """ingest writes the file the hook reads."""
    (tmp_path / ".codecompass").mkdir()
    cc_main._write_file_index(str(tmp_path), {"src/a.py": "id1", "b.py": "id2"})
    written = (tmp_path / ".codecompass" / "files.txt").read_text().splitlines()
    assert written == ["b.py", "src/a.py"]  # sorted, forward slashes


def test_backfill_file_index_from_existing_graph(tmp_path):
    """Repos ingested before the guard read files.txt get one at init, rather
    than silently allowing everything until their next ingest."""
    compass = tmp_path / ".codecompass"
    compass.mkdir()
    (compass / "graph.json").write_text(json.dumps({"nodes": [
        {"type": "File", "path": "src/a.py"},
        {"type": "File", "path": "b.py"},
        {"type": "Folder", "path": "src"},
        {"type": "Entity", "name": "foo"},
    ]}))

    cc_main._backfill_file_index(str(tmp_path))

    written = (compass / "files.txt").read_text().splitlines()
    assert written == ["b.py", "src/a.py"]  # File nodes only


def test_backfill_leaves_an_existing_index_alone(tmp_path):
    compass = tmp_path / ".codecompass"
    compass.mkdir()
    (compass / "graph.json").write_text(
        json.dumps({"nodes": [{"type": "File", "path": "a.py"}]}))
    (compass / "files.txt").write_text("mine.py\n")

    cc_main._backfill_file_index(str(tmp_path))

    assert (compass / "files.txt").read_text() == "mine.py\n"


def test_register_repo_appends_once(tmp_path, monkeypatch):
    registry = tmp_path / "repos"
    monkeypatch.setenv("CODECOMPASS_REPOS", str(registry))
    cc_main._register_repo(str(tmp_path))
    cc_main._register_repo(str(tmp_path))
    assert registry.read_text().splitlines() == [str(tmp_path)]
