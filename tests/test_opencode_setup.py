"""The global opencode config gets the hooks plugin under its real npm name.

`opencode-hooks-api` is the GitHub repo's title; the package publishes as
`opencode-hooks-plugin`. Configs written with the former loaded nothing, so the
guard never fired in opencode at all — hence the rewrite-in-place below.
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
    monkeypatch.setattr(opencode_setup, "_CONFIG", cfg)
    monkeypatch.setattr(opencode_setup, "_opencode_available", lambda: True)
    return cfg


def test_registers_plugin_under_its_npm_name(tmp_path, monkeypatch):
    cfg = _config(tmp_path, monkeypatch, {})
    opencode_setup.setup_opencode(quiet=True)
    assert "opencode-hooks-plugin" in json.loads(cfg.read_text())["plugin"]


def test_legacy_name_is_rewritten_not_appended(tmp_path, monkeypatch):
    cfg = _config(tmp_path, monkeypatch,
                  {"plugin": ["opencode-hooks-api", "keep-me"]})

    opencode_setup.setup_opencode(quiet=True)

    plugins = json.loads(cfg.read_text())["plugin"]
    assert "opencode-hooks-api" not in plugins  # the dead entry is gone
    assert "opencode-hooks-plugin" in plugins
    assert "keep-me" in plugins


def test_already_current_config_is_left_alone(tmp_path, monkeypatch):
    cfg = _config(tmp_path, monkeypatch, {"plugin": ["opencode-hooks-plugin"]})
    opencode_setup.setup_opencode(quiet=True)
    before = cfg.read_text()
    opencode_setup.setup_opencode(quiet=True)
    assert cfg.read_text() == before
