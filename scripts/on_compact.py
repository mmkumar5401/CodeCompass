"""PreCompact hook — trigger learnings extraction before compaction erases context.

Outputs additionalContext instructing Claude to write key learnings to
memory/learnings.md before the compaction summary is generated.
Also snapshots files changed (via git diff) so nothing structural is lost.

Wired via .claude/settings.json PreCompact hook — do not call manually.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_GRAPHRAG_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = _GRAPHRAG_ROOT / "memory"
SESSION_LOG = MEMORY_DIR / "session_log.md"


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


def _log_compact_event(session_id: str, changed_files: list[str]) -> None:
    MEMORY_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\n\n## {timestamp} (pre-compact)"]
    if session_id:
        lines.append(f"session: {session_id[:8]}")
    lines.append(f"files changed: {', '.join(changed_files) if changed_files else 'none'}")
    with open(SESSION_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    payload = _read_stdin_json() or {}
    session_id = payload.get("session_id", "")

    # Log the compact event to session_log.md
    changed_files = _get_changed_files()
    _log_compact_event(session_id, changed_files)

    # Inject instructions — Claude writes learnings before compacting
    changed_note = (
        f"Files changed this session: {', '.join(changed_files)}"
        if changed_files else ""
    )

    instruction = f"""BEFORE generating the compaction summary, do the following:

1. Review this conversation and extract the most important learnings — design decisions made,
   problems solved, constraints discovered, patterns established, insights that should persist.
2. Append them to memory/learnings.md in this exact format:

## {datetime.now().strftime('%Y-%m-%d')} (pre-compact)

- <specific learning>
- <specific learning>

Rules: maximum 8 bullets, be specific, skip routine file edits and obvious details.
{changed_note}

After writing to memory/learnings.md, proceed with the compaction summary as normal."""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": instruction,
        }
    }
    print(json.dumps(output))
    print("[on_compact] pre-compact instruction injected", file=sys.stderr)


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
