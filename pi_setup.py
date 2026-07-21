"""One-shot bootstrap that wires CodeCompass into pi.

pi has no built-in MCP support, so it reads MCP servers through the
`pi-mcp-adapter` package. This module, exposed as `codecompass setup-pi` and
auto-run on the first CLI / server invocation, does the whole chain:

    1. pi not installed  -> do nothing.
    2. pi-mcp-adapter not installed -> `pi install npm:pi-mcp-adapter`.
    3. copy the codecompass skill to the user-global pi skills dir.
    4. register the codecompass-mcp server in the user-global mcp.json.

Everything is idempotent: the presence of the installed skill file is the
marker, so repeated invocations are a cheap stat + no-op.
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
_SKILL_MD = """\
---
name: codecompass
description: Orient in any indexed repo through the CodeCompass code graph before reading files. Use for discovery, impact/dependency traces, dead-code checks, and flow analysis in any repository with a .codecompass/graph.json index.
---

# CodeCompass

CodeCompass maps a repo into a queryable graph so you orient from a compact
index instead of grepping and dumping whole files. The tools are available as
MCP tools (via pi-mcp-adapter) and as the `codecompass` CLI over bash.

Orient first: start from an entry point, trace its flow and dependencies, then
read only the specific slices the graph points you to. Do not `grep`/`cat`/`rg`
across the repo to find code.

## Index / re-index

```bash
codecompass ingest-code            # run after any code change
```

## Discovery

```bash
codecompass query --tree                          # full project tree
codecompass query --grep "^get_"                  # regex over indexed entities
```

## Trace and impact

```bash
codecompass query --impact "login()"              # callers of an entity
codecompass query --blast-radius src/auth.py      # files affected by a change
codecompass query --batch-impact "foo()" "bar()"  # union blast radius
codecompass query --deps src/auth.py              # imports/dependencies
codecompass query --flow "handle_request()"       # lean flow structure
codecompass query --flow-summary "handle_request()" # mermaid + narration
codecompass query --styles LoginForm              # CSS selectors for an element
```

## Dead code

```bash
codecompass query --dead-code
codecompass query --dead-code --include-entrypoints
```

## Other

```bash
codecompass init <repo_path>       # create .codecompass/ stubs
codecompass enrich                 # stage descriptions + missing calls (user-triggered only)
codecompass enrich --apply         # merge staged enrich results into the graph
codecompass add-entity <name> --file F --line N --description "..."  # record a parser-missed entity
codecompass add-call <caller> <callee> --line N   # record a parser-missed call edge
codecompass watch                  # keep the graph updated as files change
```

## Notes

- Commands default to the current directory; pass a repo path to run elsewhere.
- `codecompass enrich` is expensive — only run it when the user explicitly asks.
- Use `add-entity`/`add-call` opportunistically while reading; entries are marked
  `agent_inferred` and survive re-ingest. Flush what you learned before re-ingesting.
- If the graph is stale (>24h), re-run `codecompass ingest-code`.
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


def setup_pi(force: bool = False, quiet: bool = False) -> bool:
    """Bootstrap CodeCompass into pi. Returns True if pi setup is in place.

    No-op (returns False) when pi is not installed. Idempotent: the installed
    skill file is the marker, so a normal run after the first is a single stat.
    """

    def say(msg: str) -> None:
        if not quiet:
            print(msg)

    if not _pi_available():
        say("pi not installed; skipping CodeCompass pi setup.")
        return False

    if _SKILL_FILE.exists() and not force:
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
