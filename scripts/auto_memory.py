"""Claude Code Stop hook — log session metadata on close.

Fires when Claude Code stops. Records a lightweight session entry
(timestamp, session ID, files changed) to memory/session_log.md.

Learnings extraction happens when the user says "store my session" —
Claude handles that natively, no API call needed.

Wired via .claude/settings.json Stop hook — do not call manually.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_GRAPHRAG_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = _GRAPHRAG_ROOT / "memory"
SESSION_LOG = MEMORY_DIR / "session_log.md"


def main() -> None:
    payload = _read_stdin_json() or {}
    session_id = payload.get("session_id", "")

    changed_files = _get_changed_files()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    _log_session(session_id, timestamp, changed_files)
    print(f"[auto_memory] session logged to memory/session_log.md", file=sys.stderr)


def _get_changed_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(_GRAPHRAG_ROOT),
        )
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return files
    except Exception:
        return []


def _log_session(session_id: str, timestamp: str, changed_files: list[str]) -> None:
    MEMORY_DIR.mkdir(exist_ok=True)

    lines = [f"\n\n## {timestamp}"]
    if session_id:
        lines.append(f"session: {session_id[:8]}")
    if changed_files:
        lines.append(f"files changed: {', '.join(changed_files)}")
    else:
        lines.append("files changed: none")

    with open(SESSION_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _read_stdin_json() -> dict | None:
    if sys.stdin.isatty():
        return None
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    main()
