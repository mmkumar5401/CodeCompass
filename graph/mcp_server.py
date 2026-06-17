"""CodeCompass MCP Server — exposes code graph queries as native opencode tools.

Registered in ~/.config/opencode/opencode.json as a local MCP server.
Available from any working directory — no need to cd to the codecompass project.

Tools exposed:
    list_projects  — list all ingested projects
    blast_radius   — all files reachable from a symbol/file (forward)
    impact         — what calls/uses a symbol (reverse)
    deps           — what a file imports (direct + transitive)
    trace          — forward call chain from a function
    tree           — folder/file hierarchy for a project
    styles         — CSS selectors that target an element
    batch_impact   — union blast radius for N targets (plan a PR)

Usage:
    python -m graph.mcp_server
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from mcp.server.fastmcp import FastMCP

from graph.code_graph_client import get_client

mcp = FastMCP("codecompass")
DEFAULT_HOPS = 3
STALE_WARN_HOURS = 24


def _stale_warning(project: str) -> str:
    client = get_client(project)
    try:
        ts = client.get_project_last_ingested(project)
    finally:
        client.close()
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if age_hours > STALE_WARN_HOURS:
            return f"\nWARNING: index for '{project}' is {age_hours:.0f}h old — re-run ingest-code to refresh"
    except (ValueError, TypeError):
        pass
    return ""


# ── list_projects ────────────────────────────────────────────────────────────


@mcp.tool()
def list_projects() -> str:
    """List all projects currently ingested in the code graph."""
    client = get_client("default")
    try:
        projects = client.get_all_projects()
    finally:
        client.close()

    if not projects:
        return "No projects ingested yet.\n  Run: python main.py ingest-code <repo_path> --project <name>"

    return "Ingested projects:\n" + "\n".join(f"  {p}" for p in projects)


# ── impact ───────────────────────────────────────────────────────────────────


@mcp.tool()
def impact(symbol: str, project: str, hops: int = DEFAULT_HOPS) -> str:
    """What calls or uses a symbol? Reverse traversal — find everything that
    references a function, class, CSS variable, or HTML element."""
    client = get_client(project)
    try:
        rows = client.find_callers(symbol, project, max_hops=hops)
    finally:
        client.close()

    if not rows:
        return f"Nothing calls '{symbol}' within {hops} hops."

    lines = [f"Callers of '{symbol}':"]
    for r in rows:
        tag = f"({r.get('caller_type', '')})" if r.get("caller_type") else ""
        lines.append(f"  {r['caller_name']} {tag}in {r['caller_file']} [depth {r['depth']}]")

    lines.append(_stale_warning(project))
    return "\n".join(lines)


# ── deps ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def deps(file_path: str, project: str, hops: int = DEFAULT_HOPS) -> str:
    """What does a file import? Returns direct and transitive dependencies."""
    client = get_client(project)
    try:
        rows = client.find_dependencies(file_path, project, max_hops=hops)
    finally:
        client.close()

    if not rows:
        return f"No dependencies found for '{file_path}'."

    lines = [f"Dependencies of '{file_path}':"]
    for r in rows:
        tag = f"({r.get('dep_type', '')})" if r.get("dep_type") else ""
        lines.append(f"  {r['dependency']} {tag}[depth {r['depth']}]")

    lines.append(_stale_warning(project))
    return "\n".join(lines)


# ── styles ───────────────────────────────────────────────────────────────────


@mcp.tool()
def styles(element_name: str, project: str) -> str:
    """CSS selectors that style an HTML element or web component."""
    client = get_client(project)
    try:
        rows = client.find_styles(element_name, project)
    finally:
        client.close()

    if not rows:
        return f"No CSS selectors found for '{element_name}'."

    lines = [f"CSS selectors for '{element_name}':"]
    for r in rows:
        line_info = f" line {r['line']}" if r.get("line") else ""
        lines.append(f"  {r['selector']} in {r['source_file']}{line_info}")

    lines.append(_stale_warning(project))
    return "\n".join(lines)


# ── trace ────────────────────────────────────────────────────────────────────


@mcp.tool()
def trace(start_name: str, project: str, hops: int = 4) -> str:
    """Forward call chain — what functions does this entry point call?"""
    client = get_client(project)
    try:
        rows = client.trace_calls(start_name, project, max_hops=hops)
    finally:
        client.close()

    if not rows:
        return f"No call chain found from '{start_name}' within {hops} hops."

    lines = [f"Call chain from '{start_name}':"]
    for r in rows:
        tag = f"({r.get('callee_type', '')})" if r.get("callee_type") else ""
        lines.append(f"  {r['callee_name']} {tag}in {r['callee_file']} [depth {r['depth']}]")

    lines.append(_stale_warning(project))
    return "\n".join(lines)


# ── blast_radius ─────────────────────────────────────────────────────────────


@mcp.tool()
def blast_radius(target: str, project: str, hops: int = DEFAULT_HOPS) -> str:
    """All files reachable from a symbol or file via CALLS/IMPORTS/INHERITS.
    Use before editing — shows everything a change will touch."""
    client = get_client(project)
    try:
        rows, target_file = client.get_blast_radius(target, project, max_hops=hops)
    finally:
        client.close()

    if target_file is None and not rows:
        return f"'{target}' not found in project '{project}'."

    lines = [f"Blast radius for '{target}' (via {target_file or 'unknown file'}):"]
    if not rows:
        lines.append("  (nothing reachable within hops)")

    seen = set()
    for r in rows:
        f = r["file"]
        if f not in seen:
            seen.add(f)
            lines.append(f"  {f}  [via: {r.get('edge_type', '?')}]")

    lines.append(f"\n# blast radius: {len(seen)} files across {hops} hops")
    lines.append(_stale_warning(project))
    return "\n".join(lines)


# ── batch_impact ─────────────────────────────────────────────────────────────


@mcp.tool()
def batch_impact(targets: str, project: str, hops: int = DEFAULT_HOPS) -> str:
    """Union blast radius across multiple targets (comma-separated).
    Use when planning a PR — see the full set of files touched."""
    target_list = [t.strip() for t in targets.split(",") if t.strip()]

    client = get_client(project)
    try:
        all_files: set[str] = set()
        lines = [f"Batch impact for {len(target_list)} targets in '{project}':"]
        found_any = False

        for target in target_list:
            rows, target_file = client.get_blast_radius(target, project, max_hops=hops)
            if target_file is None and not rows:
                lines.append(f"  WARNING: '{target}' not found")
                continue
            found_any = True
            for r in rows:
                if r["file"] not in all_files:
                    all_files.add(r["file"])
                    lines.append(f"  {r['file']}  [via: {target}]")

        if not found_any:
            return f"None of the targets found in project '{project}'."

        lines.append(f"\n# batch impact: {len(all_files)} files, {len(target_list)} input targets, {hops} hops")
    finally:
        client.close()

    lines.append(_stale_warning(project))
    return "\n".join(lines)


# ── tree ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def tree(project: str) -> str:
    """Folder and file hierarchy for a project."""
    client = get_client(project)
    try:
        rows = client.get_project_tree(project)
    finally:
        client.close()

    if not rows:
        return f"No hierarchy found for project '{project}'. Run ingest-code first."

    lines = [project + "/"]
    for r in rows:
        indent = "  " * (r.get("depth", 0) or 0)
        name = r["name"]
        node_type = r.get("node_type", "")
        suffix = "/" if node_type == "Folder" else ""
        lines.append(f"{indent}├── {name}{suffix}")

    lines.append(_stale_warning(project))
    return "\n".join(lines)


# ── entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
