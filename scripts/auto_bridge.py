"""Claude Code PostToolUse Bash hook — bridge doc concepts to code entities.

Fires after any Bash command. Checks if the command ran ingest_cli.py or
remember_batch_cli.py. If so, compares doc graph nodes against the code graph
and uses Claude to find semantic links between them.

Wired via .claude/settings.json PostToolUse hook — do not call manually.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_GRAPHRAG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GRAPHRAG_ROOT))

from dotenv import load_dotenv
load_dotenv(_GRAPHRAG_ROOT / ".env", override=True)

GRAPHRAG_ROOT = str(_GRAPHRAG_ROOT)
CODE_PROJECT = "graphrag"
MAX_NODES = 3500


def main() -> None:
    payload = _read_stdin_json() or {}

    command = payload.get("tool_input", {}).get("command", "")
    is_ingest = "ingest_cli" in command or "remember_batch_cli" in command
    if not is_ingest:
        return

    print(f"[auto_bridge] ingestion detected, scanning for doc↔code bridges...", file=sys.stderr)

    doc_nodes = _run_cmd([sys.executable, "graph/query_cli.py", "--list-nodes"])
    if not doc_nodes or "No relevant" in doc_nodes:
        print("[auto_bridge] doc graph empty, skipping", file=sys.stderr)
        return

    code_tree = _run_cmd(
        [sys.executable, "-m", "graph.code_query_cli", "--tree", CODE_PROJECT, "--plain"]
    )
    if not code_tree:
        print("[auto_bridge] code graph empty, skipping", file=sys.stderr)
        return

    prompt = (
        "You are analyzing a knowledge graph system with two separate graphs:\n\n"
        "1. DOC GRAPH — concepts extracted from papers and documents:\n"
        f"{doc_nodes[:MAX_NODES]}\n\n"
        "2. CODE GRAPH — entities from the graphrag source code:\n"
        f"{code_tree[:MAX_NODES]}\n\n"
        "Find semantic bridges between doc concepts and code entities.\n"
        "A bridge exists when a code entity directly IMPLEMENTS, APPLIES, or "
        "IS_DESCRIBED_BY a doc concept — not just a vague thematic similarity.\n\n"
        "Return ONLY a JSON array, or [] if no high-confidence bridges found:\n"
        '[{"from": "code_entity", "relation": "IMPLEMENTS", "to": "DocConcept"}]\n\n'
        "Valid relations: IMPLEMENTS, APPLIES, IS_DESCRIBED_BY, MAPS_TO, INSPIRED_BY\n"
        "Rules:\n"
        "- Only include specific, verifiable links — not guesses\n"
        "- from = code entity name, to = doc concept name (use exact names from the lists)\n"
        "- Maximum 15 bridges"
    )

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        capture_output=True, text=True, timeout=120, cwd=GRAPHRAG_ROOT,
        stdin=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        print(f"[auto_bridge] claude -p failed: {result.stderr[:300]}", file=sys.stderr)
        return

    text = _extract_result_text(result.stdout)
    triples = _extract_triples(text)
    if not triples:
        print("[auto_bridge] no doc↔code bridges found", file=sys.stderr)
        return

    triples_json = json.dumps(triples)
    write = subprocess.run(
        [sys.executable, "graph/remember_batch_cli.py", triples_json],
        capture_output=True, text=True, cwd=GRAPHRAG_ROOT,
    )
    print(f"[auto_bridge] wrote {len(triples)} doc↔code links to graph", file=sys.stderr)
    if write.stdout:
        print(write.stdout, file=sys.stderr)


def _run_cmd(cmd: list[str]) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=GRAPHRAG_ROOT
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


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


def _extract_triples(text: str) -> list:
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
    return []


if __name__ == "__main__":
    main()
