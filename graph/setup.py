"""CodeCompass setup wizard — writes all config files a pip-installed agent needs.

Usage:
    codecompass setup
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

INSTRUCTIONS_MD = """\
# CodeCompass — opencode Instructions

A Neo4j-backed code dependency graph is available via MCP tools. \
**Always query it before editing code.** The graph knows what's connected — \
trust it over file exploration.

---

## Available tools (MCP)

All tools use the `codecompass` MCP server. Call them from any working directory.

| Tool | Purpose |
|---|---|
| `list_projects` | See all ingested projects |
| `blast_radius` | Every file a symbol/file touches (forward) |
| `impact` | What calls/uses a symbol (reverse) |
| `deps` | What a file imports |
| `trace` | Forward call chain from a function |
| `tree` | Folder/file hierarchy |
| `styles` | CSS selectors for an element |
| `batch_impact` | Union blast radius across N targets |

---

## When to use each tool

| Scenario | Tool to call first |
|---|---|
| About to edit one file or symbol | `blast_radius(symbol, project)` |
| Planning a PR touching N files | `batch_impact("file1, file2", project)` |
| Renaming or removing a function | `impact(function_name, project)` |
| Understanding what a file imports | `deps(file_path, project)` |
| Tracing a call chain forward | `trace(entry_point, project)` |
| Orienting in an unfamiliar project | `tree(project)` |
| Finding which CSS targets an element | `styles(element_name, project)` |
| Discovering ingested projects | `list_projects()` |

---

## Mandatory rules

1. **Before editing any file in an ingested project, call the codecompass tools first.**
2. Use `list_projects()` to discover what projects are available.
3. Use `blast_radius` to understand impact before making changes.
4. Use `impact` before renaming or removing anything.
5. If a tool returns a WARNING about stale index, suggest re-running `codecompass ingest-code`.
6. The graph provides **structural truth** (AST-parsed). Trust it. It cannot tell you what code *means* — only what's connected.

---

## Project memory

Session learnings are stored in `memory/learnings.md`. Design decisions are in \
`memory/decisions.md`. These accumulate across sessions — read them at session \
start if relevant to your task.
"""

DOT_ENV_TEMPLATE = """\
ANTHROPIC_API_KEY=your_key_here
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
"""


def _memory_plugin_ts(script_dir: str) -> str:
    return f"""\
import type {{ Plugin }} from "@opencode-ai/plugin"

const SAVE_SCRIPT = "{script_dir}/save_learnings.py"
const LOG_SCRIPT = "{script_dir}/log_session.py"

export const CodeCompassMemory: Plugin = async ({{ $, directory }}) => {{
  return {{
    "experimental.session.compacting": async (_input, output) => {{
      output.context.push(`## CodeCompass Session Memory

Before generating the compaction summary, review this conversation and include:

### Key Learnings
- Design decisions made and why
- Problems solved and how
- Constraints discovered
- Patterns established
- Non-obvious insights

### Active Context
- Current task and its status
- Files being modified
- Blockers or dependencies

Format the learnings section so they can be extracted later if needed.`)
    }},

    event: async ({{ event }}) => {{
      if (event.type === "session.idle") {{
        await $`python ${{LOG_SCRIPT}} ${{directory}}`.quiet().nothrow()
      }}
      if (event.type === "session.compacted") {{
        await $`python ${{SAVE_SCRIPT}} ${{directory}}`.quiet().nothrow()
      }}
    }},
  }}
}}
"""


def _save_learnings_py(memory_dir: str) -> str:
    return f"""\
from __future__ import annotations

import subprocess, sys
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path("{memory_dir}")
LEARNINGS_FILE = MEMORY_DIR / "learnings.md"


def _get_changed_files(cwd: str) -> list[str]:
    try:
        r = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=cwd)
        return [f.strip() for f in r.stdout.strip().split("\\n") if f.strip()]
    except Exception:
        return []


def main() -> None:
    cwd = sys.argv[1] if len(sys.argv) > 1 else __import__("os").getcwd()
    changed = _get_changed_files(cwd)
    date_key = datetime.now().strftime("%Y-%m-%d")
    lines = [f"\\n\\n## {{date_key}} (post-compact)", f"cwd: {{cwd}}"]
    if changed:
        lines.append(f"Files changed: {{', '.join(changed)}}")
        lines.append(f"- (review conversation for key learnings about: {{', '.join(changed[:3])}})")
    else:
        lines.append("Session compacted — no file changes detected.")
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEARNINGS_FILE, "a", encoding="utf-8") as f:
        f.write("\\n".join(lines) + "\\n")


if __name__ == "__main__":
    main()
"""


def _log_session_py(memory_dir: str) -> str:
    return f"""\
from __future__ import annotations

import subprocess, sys
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path("{memory_dir}")
SESSION_LOG = MEMORY_DIR / "session_log.md"


def _get_changed_files(cwd: str) -> list[str]:
    try:
        r = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=cwd)
        return [f.strip() for f in r.stdout.strip().split("\\n") if f.strip()]
    except Exception:
        return []


def main() -> None:
    cwd = sys.argv[1] if len(sys.argv) > 1 else __import__("os").getcwd()
    changed = _get_changed_files(cwd)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\\n\\n## {{timestamp}}", f"cwd: {{cwd}}"]
    lines.append(f"files changed: {{', '.join(changed) if changed else 'none'}}")
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSION_LOG, "a", encoding="utf-8") as f:
        f.write("\\n".join(lines) + "\\n")


if __name__ == "__main__":
    main()
"""


def run_setup() -> None:
    base_dir = Path.home() / ".config" / "opencode" / "codecompass"
    plugins_dir = base_dir / "plugins"
    scripts_dir = base_dir / "scripts"
    memory_dir = base_dir / "memory"

    for d in (plugins_dir, scripts_dir, memory_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Write instructions
    instructions_path = base_dir / "instructions.md"
    instructions_path.write_text(INSTRUCTIONS_MD)
    print(f"Wrote {instructions_path}")

    # 2. Write memory plugin
    plugin_path = plugins_dir / "memory.ts"
    plugin_path.write_text(_memory_plugin_ts(str(scripts_dir)))
    print(f"Wrote {plugin_path}")

    # 3. Write helper scripts
    (scripts_dir / "save_learnings.py").write_text(_save_learnings_py(str(memory_dir)))
    (scripts_dir / "log_session.py").write_text(_log_session_py(str(memory_dir)))
    print(f"Wrote scripts to {scripts_dir}/")

    # 4. Write .env template
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        print(f".env exists at {env_path} — skipping")
    else:
        env_path.write_text(DOT_ENV_TEMPLATE)
        print(f"Created {env_path}")

    # 5. Print opencode config
    config_block = {
        "instructions": [str(instructions_path)],
        "mcp": {
            "codecompass": {
                "type": "local",
                "command": ["codecompass-mcp"]
            }
        },
        "plugin": [str(plugin_path)]
    }

    opencode_config = Path.home() / ".config" / "opencode" / "opencode.json"
    print()
    if opencode_config.exists():
        print(f"Merge this into {opencode_config}:")
    else:
        print(f"Add this to {opencode_config}:")
    print()
    print(json.dumps(config_block, indent=2))
    print()
    print("Restart opencode. Then: opencode")
    print('Ask "what ingested projects are available?" — it should use list_projects.')
