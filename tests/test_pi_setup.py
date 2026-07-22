"""The pi skill file self-updates on upgrade, but never clobbers a user's copy;
the mcp.json entry always points at a command pi can actually spawn."""

import json

import pi_setup


def test_skill_frontmatter_is_first():
    """pi parses YAML frontmatter only when `---` is line 1 — anything above it
    (like our generated-by marker) makes it report "description is required"."""
    lines = pi_setup._SKILL_MD.splitlines()
    assert lines[0] == "---"
    assert any(line.startswith("description:") for line in lines[:5])
    closing = lines.index("---", 1)
    assert pi_setup._SKILL_MARKER in lines[closing + 1]  # marker sits in the body


def _install(tmp_path, monkeypatch):
    """Point pi_setup at a temp home and pretend pi + adapter are installed."""
    skill_file = tmp_path / "SKILL.md"
    monkeypatch.setattr(pi_setup, "_SKILL_DIR", tmp_path)
    monkeypatch.setattr(pi_setup, "_SKILL_FILE", skill_file)
    monkeypatch.setattr(pi_setup, "_MCP_CONFIG", tmp_path / "mcp.json")
    monkeypatch.setattr(pi_setup, "_pi_available", lambda: True)
    monkeypatch.setattr(pi_setup, "_adapter_installed", lambda: True)
    return skill_file


def test_stale_skill_is_rewritten_but_user_edits_are_kept(tmp_path, monkeypatch):
    skill_file = _install(tmp_path, monkeypatch)

    assert pi_setup.setup_pi(quiet=True) is True
    assert skill_file.read_text() == pi_setup._SKILL_MD

    # An older release's text — marker present, content stale -> rewritten.
    skill_file.write_text(pi_setup._SKILL_MARKER + "\nold instructions\n")
    pi_setup.setup_pi(quiet=True)
    assert skill_file.read_text() == pi_setup._SKILL_MD

    # The user took ownership by stripping the marker -> left alone.
    skill_file.write_text("my own skill\n")
    pi_setup.setup_pi(quiet=True)
    assert skill_file.read_text() == "my own skill\n"

    # ...unless explicitly forced.
    pi_setup.setup_pi(force=True, quiet=True)
    assert skill_file.read_text() == pi_setup._SKILL_MD


def test_pre_marker_skill_is_adopted_and_updated(tmp_path, monkeypatch):
    """A copy installed before the marker existed is still ours to replace."""
    skill_file = _install(tmp_path, monkeypatch)
    skill_file.write_text(
        "---\nname: codecompass\n---\n\n"
        "CodeCompass maps a repo into a queryable graph so you orient...\n"
    )

    pi_setup.setup_pi(quiet=True)
    assert skill_file.read_text() == pi_setup._SKILL_MD


def test_mcp_config_points_at_an_absolute_command(tmp_path, monkeypatch):
    """A bare name resolves through PATH/pyenv and can land on a Python that
    doesn't have codecompass installed — pin the interpreter's own script."""
    _install(tmp_path, monkeypatch)
    config = tmp_path / "mcp.json"

    script = tmp_path / "codecompass-mcp"
    script.write_text("#!/bin/sh\n")
    monkeypatch.setattr(pi_setup.sys, "executable", str(tmp_path / "python"))

    pi_setup.setup_pi(quiet=True)
    entry = json.loads(config.read_text())["mcpServers"]["codecompass"]
    assert entry == {"command": str(script)}

    # Other servers in the file are preserved, and a stale codecompass entry is
    # corrected even when the skill file is already up to date.
    config.write_text(json.dumps({"mcpServers": {
        "other": {"command": "keep-me"},
        "codecompass": {"command": "codecompass-mcp"},
    }}))
    pi_setup.setup_pi(quiet=True)
    servers = json.loads(config.read_text())["mcpServers"]
    assert servers["other"] == {"command": "keep-me"}
    assert servers["codecompass"] == {"command": str(script)}


def test_no_pi_no_write(tmp_path, monkeypatch):
    skill_file = _install(tmp_path, monkeypatch)
    monkeypatch.setattr(pi_setup, "_pi_available", lambda: False)
    assert pi_setup.setup_pi(quiet=True) is False
    assert not skill_file.exists()
