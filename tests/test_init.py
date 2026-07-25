"""init refreshes generated artifacts but leaves user files and graph.json alone."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import init_project


def test_init_refreshes_generated_keeps_user_and_graph(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pi")  # pretend pi exists

    init_project(str(repo))

    graph = repo / ".codecompass" / "graph.json"
    graph.write_text('{"sentinel": true}\n')
    overview = repo / ".codecompass" / "overview.md"
    overview.write_text("# my notes\n")

    # plant stale generated copies (marker-bearing)
    canonical = repo / ".agents" / "codecompass.md"
    canonical.write_text(canonical.read_text().replace("Code graph", "OLD VERSION"))
    hook = repo / ".agents" / "hooks" / "block-file-search.py"
    hook.write_text(hook.read_text().replace("MCP tools", "OLD VERSION"))
    claude_md = repo / ".claude" / "CLAUDE.md"
    claude_md.write_text(claude_md.read_text().replace("Read `.agents", "OLD Read `.agents"))
    # legacy locations from pre-7.0 init — should be cleaned up
    legacy_claude = repo / "claude.md"
    legacy_claude.write_text("AGENTS.md\n\nOrient through the code graph first: OLD.\n")
    legacy_pi = repo / ".pi" / "agent" / "AGENTS.md"
    legacy_pi.parent.mkdir(parents=True, exist_ok=True)
    legacy_pi.write_text("See AGENTS.md in the project root — OLD.\n")
    # legacy artifacts from older versions — should be cleaned up
    legacy_hook = repo / ".claude" / "hooks" / "block-file-search.py"
    legacy_hook.parent.mkdir(parents=True, exist_ok=True)
    legacy_hook.write_text("# Installed by `codecompass init` — OLD\n")
    legacy_ext = repo / ".pi" / "extensions" / "codecompass-guard.ts"
    legacy_ext.parent.mkdir(parents=True, exist_ok=True)
    legacy_ext.write_text("// Installed by the codecompass `init` tool — OLD\n")

    # user-authored files
    user_ext = repo / ".pi" / "extensions" / "mine.ts"
    user_ext.write_text("// mine\n")

    init_project(str(repo))

    assert "OLD VERSION" not in canonical.read_text()
    assert "OLD VERSION" not in hook.read_text()
    assert "OLD" not in claude_md.read_text()
    assert not legacy_claude.exists()
    assert not legacy_pi.exists()
    assert (repo / ".pi" / "SYSTEM.md").exists()
    assert not legacy_hook.exists()
    assert not legacy_ext.exists()
    assert user_ext.read_text() == "// mine\n"
    assert overview.read_text() == "# my notes\n"
    assert graph.read_text() == '{"sentinel": true}\n'


def test_guard_wiring_lands_in_settings_files(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pi")
    monkeypatch.setattr("main._opencode_installed", lambda: True)

    init_project(str(repo))

    claude = json.loads((repo / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for e in claude["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert any(".agents/hooks/block-file-search.py" in c for c in cmds)
    assert not any(".claude/hooks" in c for c in cmds)

    pi = json.loads((repo / ".pi" / "settings.json").read_text())
    cmds = [h["command"] for e in pi["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert cmds == [f'python3 "{repo}/.agents/hooks/block-file-search.py"']

    # opencode reuses the .claude/settings.json hooks via the plugin — init only
    # registers the plugin in opencode.json
    oc = json.loads((repo / "opencode.json").read_text())
    assert oc["plugin"] == ["opencode-hooks-api"]

    # existing user hooks survive a re-init
    pi["hooks"]["PreToolUse"].append({"matcher": "write", "hooks": [
        {"type": "command", "command": "echo mine"}]})
    (repo / ".pi" / "settings.json").write_text(json.dumps(pi))
    init_project(str(repo))
    pi = json.loads((repo / ".pi" / "settings.json").read_text())
    assert any(e.get("matcher") == "write" for e in pi["hooks"]["PreToolUse"])


def test_legacy_claude_matchers_and_paths_are_migrated(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # no pi, no opencode

    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command",
                 "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/block-file-search.py"'}]},
            {"matcher": "Write", "hooks": [
                {"type": "command", "command": "echo mine"}]},
        ]}}))

    init_project(str(repo))

    pre = json.loads((claude_dir / "settings.json").read_text())["hooks"]["PreToolUse"]
    ours = [e for e in pre if "block-file-search.py" in json.dumps(e)]
    assert all(e["matcher"].startswith("^(") for e in ours)
    assert all('"${CLAUDE_PROJECT_DIR:-.}' in h["command"]
               for e in ours for h in e["hooks"])
    assert any(e.get("matcher") == "Write" for e in pre)  # user entry untouched


def test_pi_files_land_even_when_pi_is_not_on_path(tmp_path, monkeypatch):
    """pi spawning the MCP server doesn't pass its own bin dir down, so `which`
    finds nothing in the process pi asked to run init. ~/.pi is the real signal."""
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    (home / ".pi").mkdir(parents=True)
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("shutil.which", lambda _: None)  # pi is installed, just not visible

    init_project(str(repo))

    assert (repo / ".pi" / "settings.json").exists()
    assert (repo / ".pi" / "SYSTEM.md").exists()


def test_no_pi_no_pi_files(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # no ~/.pi
    monkeypatch.setattr("shutil.which", lambda _: None)

    init_project(str(repo))

    assert not (repo / ".pi").exists()


def test_stale_project_is_reinitialized_on_first_tool_call(tmp_path, monkeypatch):
    """A repo set up by an older codecompass keeps its .codecompass/ forever, so
    presence alone can't gate init — the canonical .agents/ block is the signal."""
    import mcp_server
    from main import agents_md_is_current

    repo = tmp_path / "repo"
    (repo / ".codecompass").mkdir(parents=True)
    (repo / "AGENTS.md").write_text(
        "<!-- codecompass-code-graph-start -->\n"
        "## Code graph\n\nRun `codecompass query --blast-radius <file>`.\n"
        "<!-- codecompass-code-graph-end -->\n")
    home = tmp_path / "home"
    (home / ".pi").mkdir(parents=True)
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("shutil.which", lambda _: None)

    assert not agents_md_is_current(str(repo))

    mcp_server._ensure_initialized(str(repo))

    assert agents_md_is_current(str(repo))
    assert "--blast-radius" not in (repo / "AGENTS.md").read_text()
    assert (repo / ".agents" / "codecompass.md").exists()
    assert (repo / ".agents" / "hooks" / "block-file-search.py").exists()
    assert (repo / ".pi" / "settings.json").exists()
    assert (repo / ".claude" / "settings.json").exists()
