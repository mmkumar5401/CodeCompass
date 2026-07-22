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

import functools
import os
from pathlib import Path

import anyio.from_thread
import anyio.to_thread
from fastmcp import Context, FastMCP

from graph.code_queries import (
    DEFAULT_HOPS,
    fetch_blast_radius,
    fetch_batch_impact,
    fetch_dead_code,
    fetch_deps,
    fetch_flow,
    fetch_flow_summary,
    fetch_grep,
    fetch_impact,
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


# Attached to every read result: exploring is when the agent learns what the
# parser missed, so the reminder to write it back rides along with the answer.
_RECORD_NUDGE = (
    "If in your exploration of the code and the codecompass graph if you felt "
    "anything was missing which if added could make the graph more helpful "
    "please add it using add_call add_entity. It can be entities, imports, "
    "calls, description, anything."
)


def _tool(fetch_fn, *args, **kwargs):
    """Resolve the active repo, ensure it is initialized, and call a fetch helper."""
    repo = _active_repo()
    _ensure_initialized(repo)
    result = fetch_fn(*args, repo, os.path.basename(repo), **kwargs)
    if isinstance(result, dict):
        result.setdefault("next", _RECORD_NUDGE)
    return result


@mcp.tool()
def blast_radius(target: str, hops: int = DEFAULT_HOPS) -> dict:
    """Return every file that DEPENDS ON the target — its dependents, traversed in
    reverse and transitively (who calls / imports / inherits from it).

    Use this before editing a file or symbol to see what would be affected. An
    entry point with no dependents (nothing imports it) returns few/none — that's
    correct, not empty. This is the opposite direction from `deps`.
    """
    return _tool(fetch_blast_radius, target, max_hops=hops)


@mcp.tool()
def batch_impact(targets: list[str], hops: int = DEFAULT_HOPS) -> dict:
    """Union of blast radii across multiple files or symbols.

    Useful for multi-file PRs: pass the changed files and get the combined
    set of files that may be impacted.
    """
    return _tool(fetch_batch_impact, targets, max_hops=hops)


@mcp.tool()
def impact(symbol: str, hops: int = DEFAULT_HOPS) -> dict:
    """Find all callers and importers of a function, class, or symbol.

    Use this before renaming or removing something.
    """
    return _tool(fetch_impact, symbol, max_hops=hops)


@mcp.tool()
def deps(file_path: str, hops: int = DEFAULT_HOPS) -> dict:
    """Show what a file imports or depends on, directly and transitively."""
    return _tool(fetch_deps, file_path, max_hops=hops)


@mcp.tool()
def trace(symbol: str, hops: int = DEFAULT_HOPS) -> dict:
    """Trace the call chain forward from a function or symbol."""
    return _tool(fetch_trace, symbol, max_hops=hops)


@mcp.tool()
def styles(element: str) -> dict:
    """Find every CSS selector that styles an HTML element or class name."""
    return _tool(fetch_styles, element)


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
    return _tool(fetch_grep, pattern, field=field, ignore_case=ignore_case, limit=limit)


@mcp.tool()
def search(query: str, limit: int = 10) -> dict:
    """Semantic vector search over entities — for concepts that aren't symbol names.

    Matches the query against embedded entity name/kind/file/description, so
    it finds things like "session timeout" or "caching" even when no symbol
    carries those words. Use grep for exact names/patterns; use this when you
    have an idea, not a name. Requires the optional vector deps
    (`pip install 'codecompass-mcp[search]'`) and an ingest to build the index.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    from graph.vector_store import search_entities
    result = search_entities(repo, query, limit=limit)
    if isinstance(result, dict):
        result.setdefault("next", _RECORD_NUDGE)
    return result


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
    return _tool(fetch_flow, entry_symbol, max_hops=hops, include_external=include_external)


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
    fmt = format.lower()
    if fmt not in {"drawio", "mermaid", "json"}:
        raise ValueError(f"format must be 'drawio', 'mermaid', or 'json', got '{format}'")
    return _tool(fetch_flow_summary, entry_symbol, max_hops=hops, fmt=fmt, include_external=include_external)


@mcp.tool()
def dead_code(include_entrypoints: bool = False) -> dict:
    """Find entities with no inbound caller or importer.

    Set include_entrypoints=True to also list likely runtime entry points.
    Always verify candidates manually before deleting.
    """
    return _tool(fetch_dead_code, show_entrypoints=include_entrypoints)


@mcp.tool()
def tree() -> dict:
    """Return the full project hierarchy as a tree."""
    return _tool(fetch_tree)


@mcp.tool()
def init() -> dict:
    """Initialize .codecompass/ for the current repo and write AGENTS.md.

    Safe to call repeatedly — init rewrites every generated file (AGENTS.md
    block, claude.md instruction, guard hooks/extensions) so old versions
    auto-update. Query tools call this automatically, but exposing it lets
    the agent set up the project explicitly when asked.
    """
    repo = _active_repo()
    init_project(repo)
    return {"status": "ok", "repo": repo, "project": os.path.basename(repo)}


@mcp.tool()
async def ingest(ctx: Context, normalize: bool = False,
                 dump_triples: str | None = None) -> dict:
    """Re-index the currently configured repo and rebuild the code knowledge graph.

    normalize: normalize entity names via Haiku (slower, needs an API key).
    dump_triples: path to write the raw extracted triples as JSON instead of
    loading them into the graph (debugging the parser)."""
    repo = _active_repo()
    _ensure_initialized(repo)

    # ingest_code is blocking, so it runs in a worker thread; progress hops back
    # to the event loop from there so notifications flush while it works.
    def on_progress(pct: int, message: str) -> None:
        anyio.from_thread.run(ctx.report_progress, pct, 100, message)

    await anyio.to_thread.run_sync(
        functools.partial(ingest_code, repo, normalize=normalize,
                          dump_triples=dump_triples, on_progress=on_progress))
    return {"status": "ok", "repo": repo, "project": os.path.basename(repo),
            "normalize": normalize, "dump_triples": dump_triples,
            "next": _RECORD_NUDGE + " Then revisit .codecompass/overview.md, "
                    "memory.md, and learnings.md: update what this change made "
                    "wrong, add what it made worth knowing, delete what no "
                    "longer applies."}


@mcp.tool()
def add_entity(name: str, kind: str = "function", file: str = "",
               line: int | None = None, description: str = "",
               language: str = "") -> dict:
    """Record an entity you found while reading code that the graph missed
    (or under-described) — a function, class, or important variable the parser
    didn't capture. Fill in every field you know (kind, file, line, a one-line
    description); language is inferred from the file extension when omitted.
    Upserts by name+file and marks it agent_inferred. Use this
    opportunistically as you read code: every use makes the graph better.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    from ingestion.agent_writes import add_entity as _add
    return _add(repo, name, kind=kind, file=file, line=line,
                description=description, language=language)


@mcp.tool()
def add_call(caller: str, callee: str, line: int | None = None,
             relation: str = "CALLS") -> dict:
    """Record an edge you spotted in source that the parser missed — a call via
    dynamic dispatch, a callback, string-based lookup, a conditional import, a
    runtime-registered base class.

    relation is CALLS (default), IMPORTS, or INHERITS. Structural edges
    (CONTAINS/DEFINED_IN) are parser-owned and cannot be added. Both names must
    resolve unambiguously — ambiguous targets are skipped, never guessed.
    IMPORTS may target a stdlib or third-party module (`add_call("main",
    "pathlib", relation="IMPORTS")`); the module node is created if the graph
    has never seen it. Idempotent: existing edges of the same type are left
    alone.
    """
    repo = _active_repo()
    _ensure_initialized(repo)
    from ingestion.agent_writes import add_call as _add
    return _add(repo, caller, callee, line=line, relation=relation)


def main() -> None:
    from pi_setup import auto_setup_pi
    auto_setup_pi()
    mcp.run()


if __name__ == "__main__":
    main()
