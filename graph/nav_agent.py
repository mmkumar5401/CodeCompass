#!/usr/bin/env python3
"""
Graph Navigation Agent — finds the right files before Claude makes edits.

Given a natural language task, this agent:
  1. Routes the query to the right graph tool (code deps/impact or concept search)
  2. Reads only the files the graph identifies as relevant
  3. Prints compact context (graph summary + file contents) ready for Claude

Usage:
  python graph/nav_agent.py "add retry to the neo4j client"
  python graph/nav_agent.py "how does seed finding work in the query pipeline?"
  python graph/nav_agent.py "add a callback to file_watcher" --project graphrag
  python graph/nav_agent.py "what is ripple propagation?"  # concept query
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Ensure project root is on path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Routing heuristics
# ---------------------------------------------------------------------------

# Keywords that suggest impact analysis (what calls / depends on this)
_IMPACT_SIGNALS = [
    "callers", "caller", "impact", "breaks", "breaking", "depends on",
    "what uses", "who calls", "what calls", "affected by", "change",
]

# Keywords that suggest dependency analysis (what does this import/use)
_DEPS_SIGNALS = [
    "import", "imports", "dependency", "dependencies", "depends",
    "uses", "require", "requires", "needs", "file uses", "module uses",
    "add to", "extend", "modify", "add a", "add an", "implement", "retry",
    "hook", "callback", "parameter", "argument", "flag", "method", "logging",
    "timeout", "threshold", "language", "feature",
]

# File extensions we'll read as source files
_SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".md"}

# Known stdlib / third-party modules to skip when identifying project files
_SKIP_MODULES = {
    "os", "sys", "re", "json", "uuid", "pathlib", "typing", "datetime",
    "dataclasses", "asyncio", "subprocess", "argparse", "time", "math",
    "collections", "itertools", "functools", "copy", "io", "string",
    "anthropic", "neo4j", "rich", "tqdm", "dotenv", "tree_sitter",
    "tree_sitter_python", "tree_sitter_javascript", "tree_sitter_typescript",
    "tree_sitter_html", "tree_sitter_css", "watchdog", "PyPDF2", "pytest",
    "requests", "httpx", "pydantic", "fastapi", "flask", "django",
}


def _score_signals(task: str, signals: list[str]) -> int:
    task_lower = task.lower()
    return sum(1 for s in signals if s in task_lower)


def _extract_file_mention(task: str) -> str | None:
    """If the task explicitly mentions a .py file path, extract it."""
    match = re.search(r"[\w/]+\.py", task)
    return match.group(0) if match else None


def _all_project_files(project: str) -> list[str]:
    """Return all .py file paths in the project."""
    files = []
    for dirpath, _, filenames in os.walk(_root):
        # skip hidden dirs, __pycache__, eval, .git
        parts = Path(dirpath).relative_to(_root).parts
        if any(p.startswith(".") or p in ("__pycache__", "eval") for p in parts):
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                rel = str(Path(dirpath).relative_to(_root) / fn)
                files.append(rel)
    return files


def _extract_entity_mention(task: str, project: str) -> str | None:
    """
    Extract the most relevant file/entity from the task.
    Tries project file names first (handles 'neo4j client' → neo4j_client.py),
    then falls back to snake_case / CamelCase identifiers.
    """
    task_lower = task.lower()

    # Match against actual project file stems (e.g. "neo4j_client", "file_watcher")
    for f in _all_project_files(project):
        stem = Path(f).stem  # e.g. "neo4j_client"
        # check if the stem words appear in the task (handles "neo4j client" → "neo4j_client")
        words = stem.replace("_", " ")
        if words in task_lower or stem in task_lower:
            return stem

    # snake_case function/module names
    match = re.search(r"\b([a-z][a-z0-9]+(?:_[a-z0-9]+){1,})\b", task)
    if match:
        return match.group(1)

    # CamelCase class names
    match = re.search(r"\b([A-Z][a-zA-Z0-9]{2,})\b", task)
    if match:
        return match.group(1)

    return None


def route(task: str, project: str) -> list[tuple[str, list[str]]]:
    """
    Return a list of (label, command) pairs to run against the graph.
    May return multiple commands for thorough coverage.
    """
    commands = []
    file_hint = _extract_file_mention(task)
    entity_hint = _extract_entity_mention(task, project)
    impact_score = _score_signals(task, _IMPACT_SIGNALS)
    deps_score = _score_signals(task, _DEPS_SIGNALS)

    # Resolve the most likely file for the identified entity
    candidate = None
    if entity_hint and not file_hint:
        candidate = _entity_to_file(entity_hint, project)

    # Always run --deps on the target file — edit tasks always need the file itself
    target_file = file_hint or candidate
    if target_file:
        commands.append(("deps", [
            sys.executable, "-m", "graph.code_query_cli",
            "--deps", target_file, "--project", project, "--plain",
        ]))

    # Additionally run --impact when there are strong impact signals
    # (supplements deps, doesn't replace it)
    if impact_score > 0 and entity_hint:
        commands.append(("impact", [
            sys.executable, "-m", "graph.code_query_cli",
            "--impact", entity_hint, "--project", project, "--plain",
        ]))

    # Always also run concept search via query_cli for broader context
    commands.append(("concept", [
        sys.executable, "graph/query_cli.py", task, "--hops", "2",
    ]))

    # Deduplicate
    seen = set()
    unique = []
    for label, cmd in commands:
        key = " ".join(cmd)
        if key not in seen:
            seen.add(key)
            unique.append((label, cmd))
    return unique


def _entity_to_file(entity: str, project: str) -> str | None:
    """Best-guess file path for a snake_case entity name."""
    # Search known directories
    search_dirs = ["ingestion", "graph", "query", "models", "scripts", "utils"]
    for d in search_dirs:
        candidate = f"{d}/{entity}.py"
        if (_root / candidate).exists():
            return candidate
    return None


def run_command(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_root))
    return result.stdout.strip()


def parse_project_files(graph_output: str, project: str) -> list[str]:
    """Extract internal project file paths from graph output."""
    files = []
    seen = set()

    for line in graph_output.splitlines():
        # deps format: "  models.code_types (module) [depth N]"
        match = re.match(r"\s+([\w.]+)\s+\(module\)", line)
        if match:
            mod = match.group(1)
            if mod in _SKIP_MODULES or mod.split(".")[0] in _SKIP_MODULES:
                continue
            path = mod.replace(".", "/") + ".py"
            if (_root / path).exists() and path not in seen:
                files.append(path)
                seen.add(path)
            continue

        # impact format: "  main (function) in scripts/on_file_change.py [depth N]"
        match = re.match(r"\s+\S+\s+\(\w+\)\s+in\s+([\w/.]+\.py)", line)
        if match:
            path = match.group(1)
            if (_root / path).exists() and path not in seen:
                files.append(path)
                seen.add(path)

    return files


def read_files(file_paths: list[str]) -> str:
    parts = []
    for path in file_paths:
        full = _root / path
        try:
            content = full.read_text()
            ext = full.suffix
            lang = "python" if ext == ".py" else ext.lstrip(".")
            parts.append(f"### {path}\n```{lang}\n{content}\n```")
        except FileNotFoundError:
            parts.append(f"### {path}\n(file not found)")
    return "\n\n".join(parts)


def navigate(task: str, project: str, verbose: bool = False) -> str:
    """
    Main entry point. Returns a context string ready for Claude to consume.
    """
    commands = route(task, project)

    graph_sections = []
    all_files = []
    seen_files: set[str] = set()

    for label, cmd in commands:
        if verbose:
            print(f"[nav_agent] running {label}: {' '.join(cmd[1:])}", file=sys.stderr)

        output = run_command(cmd)
        if not output or "No relevant" in output or "Nothing calls" in output or "No imports" in output:
            continue

        graph_sections.append(f"[{label}]\n{output}")

        # Extract files only from code graph output (not concept/query_cli)
        if label in ("deps", "impact"):
            for f in parse_project_files(output, project):
                if f not in seen_files:
                    all_files.append(f)
                    seen_files.add(f)

    # Deduplicate and limit file reads
    all_files = all_files[:6]

    # Build output
    lines = [f"Task: {task}\n"]

    if graph_sections:
        lines.append("## Graph context\n")
        lines.append("\n\n".join(graph_sections))

    if all_files:
        lines.append(f"\n\n## Relevant files ({len(all_files)} identified by graph)\n")
        lines.append(read_files(all_files))
    elif not graph_sections:
        lines.append("\n(Graph returned no results — consider ingesting this codebase first.)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Graph navigation agent — finds the right files before Claude edits.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("task", help="Natural language task or question")
    parser.add_argument("--project", default="graphrag", help="Project name (default: graphrag)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show routing decisions")
    parser.add_argument("--no-files", action="store_true", help="Print graph context only, skip file reads")
    args = parser.parse_args()

    context = navigate(args.task, args.project, verbose=args.verbose)

    if args.no_files:
        # Strip file contents, keep graph sections only
        lines = context.split("\n## Relevant files")[0]
        print(lines)
    else:
        print(context)


if __name__ == "__main__":
    main()
