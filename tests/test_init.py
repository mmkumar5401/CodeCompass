"""init refreshes generated artifacts but leaves user files and graph.json alone."""
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
    (repo / "claude.md").write_text(
        "AGENTS.md\n\nOrient through the code graph first: OLD instruction.\n")
    hook = repo / ".claude" / "hooks" / "block-file-search.py"
    hook.write_text(hook.read_text().replace("MCP tools", "OLD VERSION"))
    ext = repo / ".pi" / "extensions" / "codecompass-guard.ts"
    ext.write_text(ext.read_text().replace("MCP tools", "OLD VERSION"))
    agents = repo / ".pi" / "agent" / "AGENTS.md"
    agents.write_text("See AGENTS.md in the project root — OLD.\n")

    # user-authored files
    user_ext = repo / ".pi" / "extensions" / "mine.ts"
    user_ext.write_text("// mine\n")

    init_project(str(repo))

    assert "OLD" not in (repo / "claude.md").read_text()
    assert "OLD VERSION" not in hook.read_text()
    assert "OLD VERSION" not in ext.read_text()
    assert "OLD" not in agents.read_text()
    assert user_ext.read_text() == "// mine\n"
    assert overview.read_text() == "# my notes\n"
    assert graph.read_text() == '{"sentinel": true}\n'


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

    assert (repo / ".pi" / "extensions" / "codecompass-guard.ts").exists()
    assert (repo / ".pi" / "agent" / "AGENTS.md").exists()


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
    presence alone can't gate init — the AGENTS.md block is the version signal."""
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
    assert (repo / ".pi" / "extensions" / "codecompass-guard.ts").exists()
    assert (repo / ".claude" / "hooks" / "block-file-search.py").exists()
