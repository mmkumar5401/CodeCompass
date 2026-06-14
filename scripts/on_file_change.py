"""Claude Code PostToolUse hook — re-ingests a changed file into the code graph.

Claude Code calls this after every Write or Edit tool use.
It reads a JSON payload from stdin:
  {"tool_name": "Write", "tool_input": {"file_path": "/abs/path/to/file.py", ...}}

The script re-parses only the changed file and applies the delta to Neo4j,
keeping the graph in sync without re-ingesting the whole repo.

Usage (wired up via .claude/settings.json hooks — do not call manually):
    echo '<hook_json>' | python scripts/on_file_change.py --project <name> --root <repo>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Resolve the graphrag root so this script works regardless of cwd
_GRAPHRAG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GRAPHRAG_ROOT))

from graph.code_graph_client import get_client
from ingestion.code_parser import parse_file, SUPPORTED_EXTENSIONS

# ---------------------------------------------------------------------------
# Configuration — set these to match your project
# ---------------------------------------------------------------------------

# Override via --project and --root CLI args, or set env vars:
#   GRAPHRAG_PROJECT=frontend GRAPHRAG_REPO_ROOT=/path/to/repo
DEFAULT_PROJECT = os.getenv("GRAPHRAG_PROJECT", "default")
DEFAULT_REPO_ROOT = os.getenv("GRAPHRAG_REPO_ROOT", os.getcwd())


def main() -> None:
    project, repo_root = _parse_args()

    payload = _read_stdin_json()
    if payload is None:
        # No stdin — nothing to do (e.g. dry-run call)
        return

    file_path = _extract_file_path(payload)
    if file_path is None:
        return

    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return

    if not os.path.isfile(file_path):
        # File was deleted — skip (file_watcher handles deletions separately)
        return

    rel_path = os.path.relpath(file_path, repo_root)
    print(f"[graphrag hook] re-ingesting {rel_path}", file=sys.stderr)

    client = get_client(project)
    try:
        # Remove stale entity nodes for this file
        client.delete_file_triples(rel_path, project)

        # Re-parse and write fresh triples
        new_triples = parse_file(file_path, repo_root)
        written = 0
        for triple in new_triples:
            client.write_code_triple(triple, file_node_id="", project=project)
            written += 1

        print(f"[graphrag hook] wrote {written} triples for {rel_path}", file=sys.stderr)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_args() -> tuple[str, str]:
    args = sys.argv[1:]
    project = DEFAULT_PROJECT
    repo_root = DEFAULT_REPO_ROOT

    if "--project" in args:
        idx = args.index("--project")
        if idx + 1 < len(args):
            project = args[idx + 1]

    if "--root" in args:
        idx = args.index("--root")
        if idx + 1 < len(args):
            repo_root = args[idx + 1]

    return project, os.path.abspath(repo_root)


def _read_stdin_json() -> dict | None:
    if sys.stdin.isatty():
        return None
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return None


def _extract_file_path(payload: dict) -> str | None:
    """Pull the edited file path from the Claude Code hook payload."""
    tool_input = payload.get("tool_input", {})

    # Write tool → file_path
    # Edit tool  → file_path
    file_path = tool_input.get("file_path")
    if file_path:
        return os.path.abspath(file_path)
    return None


if __name__ == "__main__":
    main()
