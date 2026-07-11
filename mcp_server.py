"""CodeCompass MCP server powered by FastMCP.

Exposes the code knowledge graph as structured MCP tools so clients can query
blast radius, impact, dependencies, dead code, and flow traces without shelling
out to the CLI.

Run:
    codecompass-mcp                           # serves cwd; switch with set_repo
    CODECOMPASS_REPO=/path/to/repo codecompass-mcp  # default to one repo
    codecompass mcp /path/to/repo             # CLI subcommand shortcut

The server defaults to the current working directory. Use `set_repo` when the
agent says "use this repo" or "cd to this repo" to point it elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp import FastMCP

from graph.code_query_cli import (
    DEFAULT_HOPS,
    fetch_blast_radius,
    fetch_batch_impact,
    fetch_dead_code,
    fetch_deps,
    fetch_flow,
    fetch_flow_summary,
    fetch_grep,
    fetch_impact,
    fetch_map,
    fetch_search,
    fetch_styles,
    fetch_trace,
    fetch_tree,
)
from main import init_project, ingest_code


def _default_repo_path() -> str:
    """Resolve the default repo path from env var or current directory.

    We deliberately do not parse sys.argv; FastMCP owns command-line arguments
    for transport selection (stdio, http, etc.).
    """
    if env_path := os.environ.get("CODECOMPASS_REPO"):
        return os.path.abspath(env_path)
    return os.path.abspath(os.getcwd())


# Module-level state: the repo the agent is currently querying.
_REPO_PATH: str | None = _default_repo_path()


mcp = FastMCP("codecompass")


@mcp.tool()
def set_repo(repo_path: str) -> dict:
    """Switch the server to a different repository.

    Use this when the user says "use this repo" or "cd to this repo".
    Relative paths are resolved against the current working directory.
    The selected path is remembered for the rest of the session.
    """
    global _REPO_PATH
    abs_path = os.path.abspath(os.path.expanduser(repo_path))
    if not Path(abs_path).exists():
        raise ValueError(f"Repository path does not exist: {abs_path}")
    _ensure_initialized(abs_path)
    _REPO_PATH = abs_path
    return {"status": "ok", "repo": _REPO_PATH, "project": os.path.basename(_REPO_PATH)}


@mcp.tool()
def get_repo() -> dict:
    """Return the currently configured repository, if any."""
    if _REPO_PATH is None:
        return {"repo": None, "message": "No repository configured. Call set_repo first."}
    return {"repo": _REPO_PATH, "project": os.path.basename(_REPO_PATH)}


def _ensure_initialized(repo_path: str) -> None:
    """Auto-init if .codecompass is missing, but do not auto-ingest."""
    if not Path(repo_path).joinpath(".codecompass").exists():
        init_project(repo_path)


def _active_repo() -> str:
    if _REPO_PATH is None:
        raise RuntimeError(
            "No repository configured. The server defaults to the working "
            "directory, or you can call set_repo to switch projects."
        )
    return _REPO_PATH


@mcp.tool()
def blast_radius(target: str, hops: int = DEFAULT_HOPS) -> dict:
    """Return every file reachable from target via CALLS/IMPORTS/INHERITS.

    Use this before editing a file or symbol to see what else is affected.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_blast_radius(target, repo, os.path.basename(repo), max_hops=hops)


@mcp.tool()
def batch_impact(targets: list[str], hops: int = DEFAULT_HOPS) -> dict:
    """Union of blast radii across multiple files or symbols.

    Useful for multi-file PRs: pass the changed files and get the combined
    set of files that may be impacted.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_batch_impact(targets, repo, os.path.basename(repo), max_hops=hops)


@mcp.tool()
def impact(symbol: str, hops: int = DEFAULT_HOPS) -> dict:
    """Find all callers and importers of a function, class, or symbol.

    Use this before renaming or removing something.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_impact(symbol, repo, os.path.basename(repo), max_hops=hops)


@mcp.tool()
def deps(file_path: str, hops: int = DEFAULT_HOPS) -> dict:
    """Show what a file imports or depends on, directly and transitively."""
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_deps(file_path, repo, os.path.basename(repo), max_hops=hops)


@mcp.tool()
def trace(symbol: str, hops: int = DEFAULT_HOPS) -> dict:
    """Trace the call chain forward from a function or symbol."""
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_trace(symbol, repo, os.path.basename(repo), max_hops=hops)


@mcp.tool()
def styles(element: str) -> dict:
    """Find every CSS selector that styles an HTML element or class name."""
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_styles(element, repo, os.path.basename(repo))


@mcp.tool()
def grep(pattern: str, field: str = "all", ignore_case: bool = True, limit: int = 100) -> dict:
    """Regex-search the graph — 'grep' over indexed entities instead of file text.

    Matches `pattern` (a Python regex) against each entity's name / file / kind /
    description (or one `field`), returning matching entities with the field that
    hit. This is the graph-native replacement for grepping source: full regex
    power over the symbols the graph knows about. Use it to find symbols by
    pattern (`^test_`, `.*Adapter$`, `handle|dispatch`), then drill in with
    impact/flow/deps.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_grep(pattern, repo, os.path.basename(repo), field=field,
                      ignore_case=ignore_case, limit=limit)


@mcp.tool()
def map(include_tests: bool = False) -> dict:
    """Compact `{file: [symbols]}` index of the codebase — the discovery entry
    point for a vague task.

    Returns every implementation symbol grouped by file, names only (a few
    thousand tokens, ~37x leaner than `tree`). Read it once and use your own
    judgment to find where a feature belongs — e.g. for "add response caching"
    you can see the request handler and the response-send functions and reason
    about where to hook in — then drill in with flow/impact/deps. Prefer this
    over keyword `search` when intent is semantic, not a literal string.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_map(repo, os.path.basename(repo), include_tests=include_tests)


@mcp.tool()
def search(query: str, limit: int = 30, kind: str = "") -> dict:
    """Find entities in the graph by keyword — start here when you don't yet know
    a symbol name.

    Matches the query against entity names, files, and descriptions and returns a
    ranked, lean candidate list (name/kind/file). This is the discovery step for a
    vague task ("caching", "request handler", "session"): search to find the
    relevant symbols, then drill in with impact/flow/deps. Optional `kind` filters
    by entity type (e.g. "function", "class").
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_search(query, repo, os.path.basename(repo), limit=limit, kind=kind or None)


@mcp.tool()
def flow(
    entry_symbol: str,
    hops: int = DEFAULT_HOPS,
    include_external: bool = False,
) -> dict:
    """Trace a call/import flow from an entry point — lean structure only.

    Returns just what an agent needs to navigate: each node's name/kind/file/
    depth and each edge's from/to/type/order/line. No embedded source or image.
    Use flow_summary when a person needs a readable walkthrough.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_flow(
        entry_symbol,
        repo,
        os.path.basename(repo),
        max_hops=hops,
        include_external=include_external,
    )


@mcp.tool()
def flow_summary(
    entry_symbol: str,
    hops: int = DEFAULT_HOPS,
    format: str = "mermaid",
    include_external: bool = False,
) -> dict:
    """Human-facing flow walkthrough: the trace plus a rendered narration.

    format "mermaid" (default) returns a Markdown flowchart + prose narration;
    "json" also embeds each function's signature, docstring, and source snippet;
    "drawio" renders a diagram. Heavier than `flow` — use for reading, not for
    an agent that just needs the call structure.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    fmt = format.lower()
    if fmt not in {"drawio", "mermaid", "json"}:
        raise ValueError(f"format must be 'drawio', 'mermaid', or 'json', got '{format}'")
    return fetch_flow_summary(
        entry_symbol,
        repo,
        os.path.basename(repo),
        max_hops=hops,
        fmt=fmt,
        include_external=include_external,
    )


@mcp.tool()
def dead_code(include_entrypoints: bool = False) -> dict:
    """Find entities with no inbound caller or importer.

    Set include_entrypoints=True to also list likely runtime entry points.
    Always verify candidates manually before deleting.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_dead_code(repo, os.path.basename(repo), show_entrypoints=include_entrypoints)


@mcp.tool()
def tree() -> dict:
    """Return the full project hierarchy as a tree."""
    repo = _active_repo()
    _ensure_initialized(repo)
    return fetch_tree(repo, os.path.basename(repo))


@mcp.tool()
def init() -> dict:
    """Initialize .codecompass/ for the current repo and write AGENTS.md.

    Safe to call repeatedly — it is a no-op if already initialized.
    Query tools call this automatically, but exposing it lets the agent set
    up the project explicitly when asked.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    return {"status": "ok", "repo": repo, "project": os.path.basename(repo)}


@mcp.tool()
def ingest() -> dict:
    """Re-index the currently configured repo and rebuild the code knowledge graph."""
    repo = _active_repo()
    _ensure_initialized(repo)
    ingest_code(repo)
    return {"status": "ok", "repo": repo, "project": os.path.basename(repo)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
