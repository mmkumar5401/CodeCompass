"""One-shot bootstrap that wires CodeCompass into opencode.

opencode has native MCP support and reads a user-global config at
~/.config/opencode/opencode.json. This module, exposed as
`codecompass setup-opencode` and auto-run on the first CLI / server
invocation, merges two entries into that file:

    1. opencode not installed -> do nothing.
    2. register the `opencode-hooks-api` plugin, so the codecompass guard
       hooks that `init` writes into a project's .claude/settings.json also
       fire inside opencode.
    3. register the codecompass-mcp server in the `mcp` section.

Everything is idempotent: only our keys are touched, user entries survive,
and an already-current file is left alone (no mtime churn).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# opencode's user-global config. Project-level opencode.json files override
# it, but the plugin + mcp entries belong globally — they apply to every repo.
_CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"

# Runs Claude Code-format hooks (what `init` writes into .claude/settings.json)
# inside opencode.
_HOOKS_PLUGIN = "opencode-hooks-api"

_SERVER_NAME = "codecompass"


def _server_command() -> str:
    """The uv-installed codecompass-mcp binary, when present.

    Same resolution as pi_setup._server_command: install.sh uses
    `uv tool install`, so ~/.local/bin/codecompass-mcp is the stable,
    venv-free path — prefer it over whatever environment runs this code.
    """
    uv_bin = Path.home() / ".local" / "bin" / "codecompass-mcp"
    if uv_bin.exists():
        return str(uv_bin)
    found = shutil.which("codecompass-mcp")
    if found:
        return found
    script = Path(sys.executable).with_name("codecompass-mcp")
    return str(script) if script.exists() else "codecompass-mcp"


def _opencode_available() -> bool:
    """opencode is on this machine. PATH alone lies when opencode spawned this
    process; its config directory is the durable marker."""
    return shutil.which("opencode") is not None or _CONFIG.parent.is_dir()


def setup_opencode(quiet: bool = False) -> bool:
    """Bootstrap CodeCompass into opencode. Returns True if setup is in place.

    No-op (returns False) when opencode is not installed. Idempotent; never
    clobbers a hand-edited-but-invalid config file.
    """

    def say(msg: str) -> None:
        if not quiet:
            print(msg)

    if not _opencode_available():
        say("opencode not installed; skipping CodeCompass opencode setup.")
        return False

    config: dict = {}
    if _CONFIG.exists():
        try:
            config = json.loads(_CONFIG.read_text())
        except (json.JSONDecodeError, OSError):
            say(f"Could not parse {_CONFIG}; leaving it untouched. Add the "
                f'"{_HOOKS_PLUGIN}" plugin and the codecompass MCP server manually.')
            return False

    changed = False

    plugins = config.setdefault("plugin", [])
    if _HOOKS_PLUGIN not in plugins:
        plugins.append(_HOOKS_PLUGIN)
        changed = True

    mcp = config.setdefault("mcp", {})
    entry = dict(mcp.get(_SERVER_NAME) or {})
    command = [_server_command()]
    if entry.get("command") != command:
        # "local" type + command array is opencode's stdio server shape; any
        # user-set options on the entry (env, enabled, timeout) are preserved.
        entry.setdefault("type", "local")
        entry["command"] = command
        entry.setdefault("enabled", True)
        mcp[_SERVER_NAME] = entry
        changed = True

    if not changed:
        return True

    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    say(f"CodeCompass wired into opencode: {_CONFIG} "
        f"(plugin: {_HOOKS_PLUGIN}, mcp: {_SERVER_NAME})")
    return True


def auto_setup_opencode() -> None:
    """Fire-and-forget bootstrap for the first CLI / server invocation. Never raises."""
    try:
        setup_opencode(quiet=True)
    except Exception:
        pass


if __name__ == "__main__":
    setup_opencode()
