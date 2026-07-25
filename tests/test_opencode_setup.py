"""The global opencode config gets the bundled Claude-hooks bridge plugin.

The bridge ships inside the package and is installed to
~/.config/opencode/plugins/codecompass-claude-hooks.js, registered by absolute
path. The old npm references (`opencode-hooks-plugin`, `opencode-hooks-api`)
installed into opencode's cache but never fired — hence the rewrite-in-place.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import opencode_setup


def _config(tmp_path, monkeypatch, contents=None):
    cfg = tmp_path / "opencode.json"
    if contents is not None:
        cfg.write_text(json.dumps(contents))
    plugin_path = tmp_path / "plugins" / "codecompass-claude-hooks.js"
    monkeypatch.setattr(opencode_setup, "_CONFIG", cfg)
    monkeypatch.setattr(opencode_setup, "_PLUGIN_DIR", plugin_path.parent)
    monkeypatch.setattr(opencode_setup, "_PLUGIN_PATH", plugin_path)
    monkeypatch.setattr(opencode_setup, "_opencode_available", lambda: True)
    return cfg, plugin_path


def test_registers_bundled_plugin_by_path(tmp_path, monkeypatch):
    cfg, plugin_path = _config(tmp_path, monkeypatch, {})
    opencode_setup.setup_opencode(quiet=True)
    assert str(plugin_path) in json.loads(cfg.read_text())["plugin"]


def test_installs_plugin_file_with_bridge_source(tmp_path, monkeypatch):
    _, plugin_path = _config(tmp_path, monkeypatch, {})
    opencode_setup.setup_opencode(quiet=True)
    assert plugin_path.read_text() == opencode_setup._PLUGIN_JS


def test_legacy_npm_names_are_rewritten_not_appended(tmp_path, monkeypatch):
    cfg, plugin_path = _config(tmp_path, monkeypatch, {
        "plugin": ["opencode-hooks-api", "opencode-hooks-plugin", "keep-me"],
    })

    opencode_setup.setup_opencode(quiet=True)

    plugins = json.loads(cfg.read_text())["plugin"]
    assert "opencode-hooks-api" not in plugins
    assert "opencode-hooks-plugin" not in plugins
    assert str(plugin_path) in plugins
    assert "keep-me" in plugins


def test_already_current_config_is_left_alone(tmp_path, monkeypatch):
    cfg, _ = _config(tmp_path, monkeypatch, {})
    opencode_setup.setup_opencode(quiet=True)
    before = cfg.read_text()
    opencode_setup.setup_opencode(quiet=True)
    assert cfg.read_text() == before
