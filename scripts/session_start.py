"""Claude Code SessionStart hook — inject project memory as additional context.

Fires at the start of every Claude Code session. Reads all markdown files from
the memory/ directory and injects them so Claude has full project context
without needing to re-derive it from the codebase.

Wired via .claude/settings.json SessionStart hook — do not call manually.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_GRAPHRAG_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = _GRAPHRAG_ROOT / "memory"


def main() -> None:
    if not MEMORY_DIR.exists():
        return

    parts: list[str] = []
    for md_file in sorted(MEMORY_DIR.glob("*.md")):
        content = md_file.read_text(errors="replace").strip()
        if content:
            parts.append(f"## {md_file.stem}\n\n{content}")

    if not parts:
        return

    combined = (
        "# GraphRAG Project Memory\n\n"
        "The following context was automatically loaded from memory/ in the repository.\n\n"
        + "\n\n---\n\n".join(parts)
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": combined,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
