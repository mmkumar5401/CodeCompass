"""GraphRAG learnings saver — writes timestamped entry to memory/learnings.md.

Triggered by the opencode plugin on session.compacted events.
Extracts changed files and writes a placeholder for the LLM to fill.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

_GRAPHRAG_ROOT = Path(__file__).resolve().parent.parent.parent
MEMORY_DIR = _GRAPHRAG_ROOT / "memory"
LEARNINGS_FILE = MEMORY_DIR / "learnings.md"


def _get_changed_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(_GRAPHRAG_ROOT),
        )
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        return []


def main() -> None:
    changed = _get_changed_files()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_key = datetime.now().strftime("%Y-%m-%d")

    lines = [f"\n\n## {date_key} (post-compact)"]
    if changed:
        lines.append(f"Files changed: {', '.join(changed)}")
        lines.append(f"- (review conversation for key learnings about: {', '.join(changed[:3])})")
    else:
        lines.append("Session compacted — no file changes detected.")

    MEMORY_DIR.mkdir(exist_ok=True)
    with open(LEARNINGS_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
