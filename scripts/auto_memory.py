"""Claude Code Stop hook — extract and save new project facts after every session.

Fires when Claude Code stops. Reads the session transcript, asks Claude to
identify new facts or decisions discovered during the session, and appends
them to memory/learnings.md in the repository.

Wired via .claude/settings.json Stop hook — do not call manually.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_GRAPHRAG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GRAPHRAG_ROOT))

GRAPHRAG_ROOT = str(_GRAPHRAG_ROOT)
MEMORY_DIR = _GRAPHRAG_ROOT / "memory"
LEARNINGS_FILE = MEMORY_DIR / "learnings.md"

# Hooks don't inherit nvm PATH — find claude via common locations
def _find_claude() -> str:
    candidates = [
        os.path.expanduser("~/.nvm/versions/node/v22.15.0/bin/claude"),
        os.path.expanduser("~/.nvm/versions/node/v20.0.0/bin/claude"),
        "/usr/local/bin/claude",
        "/usr/bin/claude",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    # Fall back: let shell resolve it (may fail if PATH is stripped)
    return "claude"

CLAUDE_BIN = _find_claude()

MAX_TRANSCRIPT_CHARS = 12000
MIN_SESSION_TURNS = 5


def main() -> None:
    payload = _read_stdin_json() or {}
    session_id = payload.get("session_id", "")

    transcript = _get_transcript(session_id)
    if not transcript:
        return

    turn_count = transcript.count("\n[assistant]:")
    if turn_count < MIN_SESSION_TURNS:
        return

    prompt = (
        "You are reviewing a Claude Code session in the graphrag project "
        "(a Neo4j knowledge graph memory system for LLMs).\n\n"
        "Extract NEW facts, decisions, or insights discovered in this session "
        "that are worth remembering for future sessions.\n\n"
        "Return a concise markdown bullet list (or empty string if nothing notable).\n"
        "Focus on: design decisions made, problems solved, patterns discovered, "
        "constraints found, or relationships between components.\n"
        "Skip: routine file edits, obvious code details, things already well-documented.\n"
        "Maximum 8 bullet points. Be specific.\n\n"
        f"Session transcript:\n{transcript}"
    )

    result = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=GRAPHRAG_ROOT,
        stdin=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        print(
            f"[auto_memory] claude failed (rc={result.returncode}): {result.stderr[:200]}",
            file=sys.stderr,
        )
        return

    text = _extract_result_text(result.stdout).strip()
    if not text or text in ("", "[]", "None"):
        print("[auto_memory] no new learnings this session", file=sys.stderr)
        return

    _append_to_learnings(text)
    print(f"[auto_memory] wrote session learnings to memory/learnings.md", file=sys.stderr)


def _append_to_learnings(content: str) -> None:
    MEMORY_DIR.mkdir(exist_ok=True)

    from datetime import date
    header = f"\n\n## {date.today().isoformat()}\n\n"

    with open(LEARNINGS_FILE, "a", encoding="utf-8") as f:
        f.write(header + content.strip() + "\n")


def _get_transcript(session_id: str) -> str:
    """Find and return last MAX_TRANSCRIPT_CHARS of the session transcript."""
    home = Path.home()
    cwd = os.getcwd()
    sanitized = cwd.lstrip("/").replace("/", "-")
    projects_dir = home / ".claude" / "projects" / sanitized

    transcript_file: Path | None = None

    if session_id and projects_dir.exists():
        candidate = projects_dir / f"{session_id}.jsonl"
        if candidate.exists():
            transcript_file = candidate

    if transcript_file is None and projects_dir.exists():
        files = sorted(
            projects_dir.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        transcript_file = files[0] if files else None

    if transcript_file is None:
        return ""

    try:
        lines = transcript_file.read_text(errors="replace").strip().split("\n")
    except OSError:
        return ""

    messages: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        entry_type = entry.get("type", "")
        if entry_type not in ("user", "assistant"):
            continue

        msg = entry.get("message", {})
        content = msg.get("content", "")

        if isinstance(content, list):
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            text = " ".join(p for p in parts if p.strip())
        else:
            text = str(content)

        if text.strip():
            messages.append(f"[{entry_type}]: {text[:500]}")

    combined = "\n".join(messages[-50:])
    return combined[-MAX_TRANSCRIPT_CHARS:]


def _read_stdin_json() -> dict | None:
    if sys.stdin.isatty():
        return None
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return None


def _extract_result_text(stdout: str) -> str:
    try:
        obj = json.loads(stdout)
        if isinstance(obj, dict):
            return obj.get("result", stdout)
    except json.JSONDecodeError:
        pass
    return stdout


if __name__ == "__main__":
    main()
