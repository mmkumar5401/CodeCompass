"""One-shot bootstrap that wires CodeCompass into pi.

pi has no built-in MCP support, so it reads MCP servers through the
`pi-mcp-adapter` package. This module, exposed as `codecompass setup-pi` and
auto-run on the first CLI / server invocation, does the whole chain:

    1. pi not installed  -> do nothing.
    2. pi-mcp-adapter not installed -> `pi install npm:pi-mcp-adapter`.
    3. copy the codecompass skill to the user-global pi skills dir.
    4. register the codecompass-mcp server in the user-global mcp.json.

Everything is idempotent. The installed skill file carries a generated-by
marker: a copy we wrote is rewritten on every run so an upgraded package ships
its new instructions, while a copy the user has edited (marker removed) is left
alone. Unchanged content short-circuits before any write.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# Where pi loads user-global skills and pi-mcp-adapter reads user-global servers.
_SKILL_DIR = Path.home() / ".pi" / "agent" / "skills" / "codecompass"
_SKILL_FILE = _SKILL_DIR / "SKILL.md"
_MCP_CONFIG = Path.home() / ".config" / "mcp" / "mcp.json"

_ADAPTER_PKG = "npm:pi-mcp-adapter"
_ADAPTER_NAME = "pi-mcp-adapter"

# The codecompass-mcp server entry merged into the user-global mcp.json.
_SERVER_CONFIG = {"command": "codecompass-mcp"}

# Shipped as the pi skill. pi has the MCP tools natively via pi-mcp-adapter;
# this teaches the orient-first discipline and lists the capabilities.
#
# The marker below is what makes the skill self-updating: init-style, we only
# overwrite files we wrote. Strip the line to take ownership of your copy.
_SKILL_MARKER = "<!-- Installed by `codecompass setup-pi` — rewritten on upgrade. -->"

_SKILL_MD = _SKILL_MARKER + """
---
name: codecompass
description: Orient in any indexed repo through the CodeCompass code graph before reading files. Use for discovery, impact/dependency traces, dead-code checks, and flow analysis in any repository with a .codecompass/graph.json index.
---

# CodeCompass

CodeCompass maps a repo into a queryable graph so you orient from a compact
index instead of grepping and dumping whole files. The graph is queried ONLY
through the codecompass MCP tools — there is no agent-facing CLI.

Orient first: start from an entry point, trace its flow and dependencies, then
read only the specific slices the graph points you to. Do not `grep`/`cat`/`rg`
across the repo to find code.

The server defaults to the current directory; call `codecompass_set_repo` to
point it at another repo.

## Index / re-index

- `codecompass_ingest` — run after any code change

## Discovery

- `codecompass_tree` — full project tree
- `codecompass_grep` — regex over indexed entities, e.g. `pattern="^get_"`

## Trace and impact

- `codecompass_impact` — callers of an entity
- `codecompass_blast_radius` — files affected by a change to a file/symbol
- `codecompass_batch_impact` — union blast radius across targets
- `codecompass_deps` — imports/dependencies of a file
- `codecompass_flow` — lean flow structure from an entry point
- `codecompass_flow_summary` — mermaid + narration, `format="json"` embeds signatures/source
- `codecompass_styles` — CSS selectors for an element
- `codecompass_dead_code` — entities with no inbound caller (`include_entrypoints=True` to also list entry points)

## Recording what the parser missed

- `codecompass_add_entity` — record a parser-missed entity (kind, file, line, description)
- `codecompass_add_call` — record a parser-missed call edge

## Notes

- Use `add_entity`/`add_call` opportunistically while reading — they are the ONLY
  way the graph gains descriptions and parser-invisible edges. Entries are marked
  `agent_inferred` and survive re-ingest. Flush what you learned before re-ingesting.
- After every ingest, also update `.codecompass/overview.md`, `memory.md`, and
  `learnings.md`: correct what changed, delete what no longer applies.
- If the graph looks stale or incomplete, re-run `codecompass_ingest`.
"""


def _pi_available() -> bool:
    return shutil.which("pi") is not None


def _adapter_installed() -> bool:
    try:
        out = subprocess.run(
            ["pi", "list"], capture_output=True, text=True, timeout=30
        )
        return _ADAPTER_NAME in (out.stdout + out.stderr)
    except Exception:
        return False


def _install_adapter() -> None:
    # Non-interactive; failures are non-fatal — the skill/config still get written.
    subprocess.run(["pi", "install", _ADAPTER_PKG], check=False, timeout=300)


def _write_mcp_config() -> None:
    """Merge the codecompass server into the user-global mcp.json, preserving others."""
    config: dict = {}
    if _MCP_CONFIG.exists():
        try:
            config = json.loads(_MCP_CONFIG.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}
    servers = config.setdefault("mcpServers", {})
    servers["codecompass"] = _SERVER_CONFIG
    _MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _MCP_CONFIG.write_text(json.dumps(config, indent=2) + "\n")


def _skill_is_current() -> bool:
    """True when the installed skill needs no write — either it is already our
    latest text, or the user has taken it over by stripping the marker."""
    try:
        existing = _SKILL_FILE.read_text()
    except OSError:
        return False
    return existing == _SKILL_MD or _SKILL_MARKER not in existing


def setup_pi(force: bool = False, quiet: bool = False) -> bool:
    """Bootstrap CodeCompass into pi. Returns True if pi setup is in place.

    No-op (returns False) when pi is not installed. Idempotent, and
    self-updating: a marker-bearing skill file we installed is rewritten when
    the package ships new text, so upgrades reach existing users. A file the
    user edited (marker gone) is never touched unless force=True.
    """

    def say(msg: str) -> None:
        if not quiet:
            print(msg)

    if not _pi_available():
        say("pi not installed; skipping CodeCompass pi setup.")
        return False

    if _skill_is_current() and not force:
        return True

    if not _adapter_installed():
        say("Installing pi-mcp-adapter...")
        _install_adapter()

    _SKILL_DIR.mkdir(parents=True, exist_ok=True)
    _SKILL_FILE.write_text(_SKILL_MD)
    _write_mcp_config()
    say(f"CodeCompass wired into pi: {_SKILL_FILE}, {_MCP_CONFIG}")
    return True


def auto_setup_pi() -> None:
    """Fire-and-forget bootstrap for the first CLI / server invocation. Never raises."""
    try:
        setup_pi(quiet=True)
    except Exception:
        pass


if __name__ == "__main__":
    setup_pi()
