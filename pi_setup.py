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
import sys
from pathlib import Path

# Where pi loads user-global skills.
_SKILL_DIR = Path.home() / ".pi" / "agent" / "skills" / "codecompass"
_SKILL_FILE = _SKILL_DIR / "SKILL.md"

# Where the server entry goes. pi reads its own ~/.pi/agent/mcp.json natively;
# ~/.config/mcp/mcp.json is only consulted by the standalone pi-mcp-adapter, so
# writing there alone left codecompass invisible to pi.
_PI_MCP_CONFIG = Path.home() / ".pi" / "agent" / "mcp.json"
_ADAPTER_MCP_CONFIG = Path.home() / ".config" / "mcp" / "mcp.json"

_ADAPTER_PKG = "npm:pi-mcp-adapter"
_ADAPTER_NAME = "pi-mcp-adapter"

def _server_command() -> str:
    """Absolute path to the codecompass-mcp console script, when we can find it.

    A bare "codecompass-mcp" only resolves if pi inherits a PATH that reaches
    this interpreter's bin dir — which it often doesn't. Under pyenv it is
    worse than missing: the shim resolves a *different* Python depending on the
    launch directory's .python-version, so pi silently gets "command not found"
    while the same name works in a shell inside the project. The script sitting
    next to sys.executable is the one belonging to the environment codecompass
    is actually installed in.
    """
    script = Path(sys.executable).with_name("codecompass-mcp")
    return str(script) if script.exists() else "codecompass-mcp"


# The codecompass-mcp server entry merged into the user-global mcp.json.
def _server_config() -> dict:
    return {"command": _server_command()}

# Shipped as the pi skill. pi has the MCP tools natively via pi-mcp-adapter;
# this teaches the orient-first discipline and lists the capabilities.
#
# The marker is what makes the skill self-updating: init-style, we only
# overwrite files we wrote. Strip the line to take ownership of your copy.
# It goes in the BODY, never above the frontmatter — pi requires the opening
# `---` on line 1 and reports "description is required" for anything else.
_SKILL_MARKER = "<!-- Installed by `codecompass setup-pi` — rewritten on upgrade. -->"

# Copies installed before the marker existed. A file carrying one of these is
# ours to replace, even without the marker — otherwise every pre-6.0.0 install
# would be pinned to its original skill text forever.
_LEGACY_SIGNATURES = (
    "CodeCompass maps a repo into a queryable graph",
)

_SKILL_MD = """\
---
name: codecompass
description: Orient in any indexed repo through the CodeCompass code graph before reading files. Use for discovery, impact/dependency traces, dead-code checks, and flow analysis in any repository with a .codecompass/graph.json index.
---
""" + _SKILL_MARKER + """

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
    """pi is on this machine. PATH alone lies: when pi spawns the MCP server it
    usually doesn't pass its own bin directory down, so `which` finds nothing in
    the very process pi launched. Its home directory is the durable marker."""
    return shutil.which("pi") is not None or (Path.home() / ".pi").is_dir()


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


def _write_one_mcp_config(path: Path) -> bool:
    """Point one mcp.json at our server, leaving everything else in it alone.

    Only the `command` key is ours: other servers stay, and any options the user
    added to the codecompass entry (`directTools`, env, args) are preserved.
    Returns True if the file changed.
    """
    config: dict = {}
    if path.exists():
        try:
            config = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return False  # hand-edited into invalid JSON — don't clobber it
    servers = config.setdefault("mcpServers", {})
    entry = dict(servers.get("codecompass") or {})
    if entry.get("command") == _server_command():
        return False
    entry["command"] = _server_command()
    servers["codecompass"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return True


def _write_mcp_config() -> bool:
    """Register the server everywhere pi might look for it.

    pi's own config is authoritative; the adapter's is updated too, but only if
    it already exists — no point creating a file for a tool that isn't in use.
    """
    changed = _write_one_mcp_config(_PI_MCP_CONFIG)
    if _ADAPTER_MCP_CONFIG.exists():
        changed = _write_one_mcp_config(_ADAPTER_MCP_CONFIG) or changed
    return changed


def _skill_is_current() -> bool:
    """True when the installed skill needs no write — either it is already our
    latest text, or it is a file the user wrote and we must not touch."""
    try:
        existing = _SKILL_FILE.read_text()
    except OSError:
        return False
    if existing == _SKILL_MD:
        return True
    ours = _SKILL_MARKER in existing or any(s in existing for s in _LEGACY_SIGNATURES)
    return not ours


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

    # Always reconcile the server entry: the path it should point at changes
    # when codecompass is reinstalled into a different environment, and a stale
    # one leaves pi with a server it cannot spawn.
    if _write_mcp_config():
        say(f"Pointed pi at {_server_command()} in {_PI_MCP_CONFIG}")

    if _skill_is_current() and not force:
        return True

    if not _adapter_installed():
        say("Installing pi-mcp-adapter...")
        _install_adapter()

    _SKILL_DIR.mkdir(parents=True, exist_ok=True)
    _SKILL_FILE.write_text(_SKILL_MD)
    say(f"CodeCompass wired into pi: {_SKILL_FILE}, {_PI_MCP_CONFIG}")
    return True


def auto_setup_pi() -> None:
    """Fire-and-forget bootstrap for the first CLI / server invocation. Never raises."""
    try:
        setup_pi(quiet=True)
    except Exception:
        pass


if __name__ == "__main__":
    setup_pi()
