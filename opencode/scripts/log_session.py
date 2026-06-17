"""CodeCompass session logger — writes lightweight metadata to memory/session_log.md.

Triggered by the opencode plugin on session.idle events.
Records timestamp + git diff summary so the session history is preserved.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

_CODECOMPASS_ROOT = Path(__file__).resolve().parent.parent.parent
MEMORY_DIR = _CODECOMPASS_ROOT / "memory"
SESSION_LOG = MEMORY_DIR / "session_log.md"


def _get_changed_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(_CODECOMPASS_ROOT),
        )
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        return []


def main() -> None:
    working_dir = sys.argv[1] if len(sys.argv) > 1 else str(_CODECOMPASS_ROOT)

    changed = _get_changed_files()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\n\n## {timestamp}"]
    lines.append(f"cwd: {working_dir}")
    lines.append(f"files changed: {', '.join(changed) if changed else 'none'}")

    MEMORY_DIR.mkdir(exist_ok=True)
    with open(SESSION_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
