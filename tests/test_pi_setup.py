"""The pi skill file self-updates on upgrade, but never clobbers a user's copy."""

import pi_setup


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


def test_no_pi_no_write(tmp_path, monkeypatch):
    skill_file = _install(tmp_path, monkeypatch)
    monkeypatch.setattr(pi_setup, "_pi_available", lambda: False)
    assert pi_setup.setup_pi(quiet=True) is False
    assert not skill_file.exists()
