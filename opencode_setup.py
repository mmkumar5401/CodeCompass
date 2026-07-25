"""One-shot bootstrap that wires CodeCompass into opencode.

opencode has native MCP support and reads a user-global config at
~/.config/opencode/opencode.json. This module, exposed as
`codecompass setup-opencode` and auto-run on the first CLI / server
invocation, merges two entries into that file:

    1. opencode not installed -> do nothing.
    2. install the bundled Claude-hooks bridge plugin into
       ~/.config/opencode/plugins/ and register it by absolute path, so the
       codecompass guard hooks that `init` writes into a project's
       .claude/settings.json also fire inside opencode.
    3. register the codecompass-mcp server in the `mcp` section.

Everything is idempotent: only our keys are touched, user entries survive,
and an already-current file is left alone (no mtime churn).

The bridge is bundled, not an npm dependency: the npm package we previously
referenced (`opencode-hooks-plugin`) installed into opencode's package cache
but its tool.execute.before handlers never fired in live sessions — an npm
indirection we don't control. A file path plugin has no resolution step, so
it loads like every other local plugin.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# opencode's user-global config. Project-level opencode.json files override
# it, but the plugin + mcp entries belong globally — they apply to every repo.
_CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"

# Absolute-path plugin installed by setup: a Claude Code-format hooks bridge,
# so the guard hooks that `init` writes into .claude/settings.json also fire
# inside opencode. Replaces the old npm reference, which never loaded.
_PLUGIN_DIR = Path.home() / ".config" / "opencode" / "plugins"
_PLUGIN_PATH = _PLUGIN_DIR / "codecompass-claude-hooks.js"
_LEGACY_HOOKS_PLUGINS = (
    "opencode-hooks-plugin",
    "opencode-hooks-api",
)

# The bridge, bundled so setup has no npm/network dependency. Reads
# ~/.claude/settings.json + project .claude/settings.json/.local, runs matching
# PreToolUse/PostToolUse command hooks, and blocks on exit code 2 or a deny
# decision in stdout JSON — the same contract Claude Code uses.
_PLUGIN_JS = r"""
import { readFileSync, existsSync } from "node:fs"
import { join } from "node:path"
import { homedir } from "node:os"

function loadSettings(dir) {
  const files = [
    join(homedir(), ".claude", "settings.json"),
    join(dir, ".claude", "settings.json"),
    join(dir, ".claude", "settings.local.json"),
  ]
  const hooks = {}
  for (const file of files) {
    if (!existsSync(file)) continue
    try {
      const cfg = JSON.parse(readFileSync(file, "utf8"))
      for (const [event, entries] of Object.entries(cfg.hooks ?? {})) {
        hooks[event] = [...(hooks[event] ?? []), ...entries]
      }
    } catch {}
  }
  return hooks
}

function matchHook(matcher, value) {
  if (value === undefined) return true
  if (!matcher || matcher === "*") return true
  try {
    return new RegExp(matcher, "i").test(value)
  } catch {
    return false
  }
}

async function runCommand(command, input) {
  const proc = Bun.spawn(["bash", "-c", command], {
    stdin: "pipe",
    stdout: "pipe",
    stderr: "pipe",
    env: { ...process.env, OPENCODE_PROJECT_DIR: input.cwd, CLAUDE_PROJECT_DIR: input.cwd },
  })
  proc.stdin.write(JSON.stringify(input))
  proc.stdin.end()
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ])
  if (exitCode === 2) return { block: true, reason: stderr.trim() || "Blocked by hook" }
  if (exitCode !== 0) return { block: false }
  const trimmed = stdout.trim()
  if (!trimmed) return { block: false }
  try {
    const out = JSON.parse(trimmed)
    const decision = out?.hookSpecificOutput?.permissionDecision
    if (out.decision === "block" || out.continue === false || out.ok === false || decision === "deny") {
      return {
        block: true,
        reason: out.stopReason ?? out.reason ?? out?.hookSpecificOutput?.permissionDecisionReason ?? "Blocked by hook",
      }
    }
  } catch {}
  return { block: false }
}

async function runEvent(entries, input, toolName) {
  for (const entry of entries ?? []) {
    if (!matchHook(entry.matcher, toolName)) continue
    for (const handler of entry.hooks ?? []) {
      if (handler.type !== "command") continue
      const r = await runCommand(handler.command, input)
      if (r.block) throw new Error(r.reason)
    }
  }
}

export const ClaudeHooksPlugin = async ({ directory }) => {
  const hooks = loadSettings(directory)
  return {
    "tool.execute.before": async (input, output) => {
      await runEvent(hooks.PreToolUse, {
        session_id: input.sessionID,
        cwd: directory,
        hook_event_name: "PreToolUse",
        tool_name: input.tool,
        tool_input: output.args ?? {},
      }, input.tool)
    },
    "tool.execute.after": async (input, output) => {
      await runEvent(hooks.PostToolUse, {
        session_id: input.sessionID,
        cwd: directory,
        hook_event_name: "PostToolUse",
        tool_name: input.tool,
        tool_input: input.args ?? {},
        tool_response: output.output,
      }, input.tool)
    },
  }
}

export default ClaudeHooksPlugin
""".lstrip()

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
                f'"{_PLUGIN_PATH}" plugin and the codecompass MCP server manually.')
            return False

    changed = False

    # Install/refresh the bundled bridge plugin. Content comparison keeps the
    # file byte-stable across runs (no mtime churn), and ships updates when a
    # new codecompass version changes _PLUGIN_JS.
    if not _PLUGIN_PATH.exists() or _PLUGIN_PATH.read_text() != _PLUGIN_JS:
        _PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        _PLUGIN_PATH.write_text(_PLUGIN_JS)

    plugins = config.setdefault("plugin", [])
    # Configs written before the bundled bridge name an npm package that
    # installs into opencode's cache but never fires. Rewrite in place instead
    # of appending beside it.
    plugin_ref = str(_PLUGIN_PATH)
    kept = [p for p in plugins if p not in _LEGACY_HOOKS_PLUGINS]
    if len(kept) != len(plugins):
        changed = True
    if plugin_ref not in kept:
        kept.append(plugin_ref)
        changed = True
    config["plugin"] = kept

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
        f"(plugin: {_PLUGIN_PATH}, mcp: {_SERVER_NAME})")
    return True


def auto_setup_opencode() -> None:
    """Fire-and-forget bootstrap for the first CLI / server invocation. Never raises."""
    try:
        setup_opencode(quiet=True)
    except Exception:
        pass


if __name__ == "__main__":
    setup_opencode()
