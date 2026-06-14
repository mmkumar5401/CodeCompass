"""Code-aware traversal CLI for the code knowledge graph.

    python -m graph.code_query_cli --impact "login()"
    python -m graph.code_query_cli --deps src/auth/login.py
    python -m graph.code_query_cli --styles LoginForm
    python -m graph.code_query_cli --trace "main()" --hops 4
    python -m graph.code_query_cli --tree frontend

Output is plain text by default (agent-friendly). Pass --rich for formatted tables.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from graph.code_graph_client import get_client
from ingestion.file_watcher import pid_file_path

console = Console()

DEFAULT_HOPS = 3
STALE_WARN_HOURS = 24


def main() -> None:
    args = _parse_args()
    rich = args.rich

    _check_neo4j(args.project)
    if not args.list_projects:
        _check_watcher(args.project)

    if args.list_projects:
        run_list_projects(rich=rich)
    elif args.impact:
        run_impact(args.impact, args.project, max_hops=args.hops, rich=rich)
    elif args.deps:
        run_deps(args.deps, args.project, max_hops=args.hops, rich=rich)
    elif args.styles:
        run_styles(args.styles, args.project, rich=rich)
    elif args.trace:
        run_trace(args.trace, args.project, max_hops=args.hops, rich=rich)
    elif args.tree:
        run_tree(args.tree, rich=rich)
    else:
        print("No query mode specified. Use --help.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Query modes
# ---------------------------------------------------------------------------

def run_list_projects(rich: bool = False) -> None:
    """List all projects currently ingested in the code graph."""
    client = get_client("default")
    try:
        projects = client.get_all_projects()
    finally:
        client.close()

    if not projects:
        print("No projects ingested yet.")
        print("  Run: python main.py ingest-code <repo_path> --project <name>")
        return

    if rich:
        console.print("\n[bold blue]Ingested projects:[/]")
        for p in projects:
            console.print(f"  [cyan]{p}[/]")
    else:
        print("Ingested projects:")
        for p in projects:
            print(f"  {p}")


def run_impact(entity_name: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Show what would break if entity_name is changed (reverse CALLS traversal)."""
    client = get_client(project)
    try:
        rows = client.find_callers(entity_name, project, max_hops)
        updated_at = _file_updated_at_for_entity(client, entity_name, project)
    finally:
        client.close()

    if not rows:
        print(f"Nothing calls '{entity_name}' within {max_hops} hops.")
        return

    stamp = _staleness_line(updated_at, rich_mode=rich)
    if rich:
        console.print(f"\n[bold blue]Impact analysis:[/] {entity_name}")
        if stamp:
            console.print(stamp)
        table = _make_table(title=f"Callers of '{entity_name}'", columns=["Caller", "Type", "File", "Depth"])
        for row in rows:
            table.add_row(row.get("caller_name",""), row.get("caller_type",""), row.get("caller_file",""), str(row.get("depth","")))
        console.print(table)
    else:
        if stamp:
            print(stamp)
        print(f"Callers of '{entity_name}':")
        for row in rows:
            print(f"  {row.get('caller_name','')} ({row.get('caller_type','')}) in {row.get('caller_file','')} [depth {row.get('depth','')}]")


def run_deps(file_path: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Show what a file imports, directly and transitively."""
    client = get_client(project)
    try:
        rows = client.find_dependencies(file_path, project, max_hops)
        updated_at = client.get_file_updated_at(file_path, project)
    finally:
        client.close()

    if not rows:
        print(f"No imports found for '{file_path}'.")
        return

    stamp = _staleness_line(updated_at, rich_mode=rich)
    if rich:
        console.print(f"\n[bold blue]Dependencies of:[/] {file_path}")
        if stamp:
            console.print(stamp)
        table = _make_table(title=f"Dependencies of '{file_path}'", columns=["Module", "Type", "Depth"])
        for row in rows:
            table.add_row(row.get("dependency",""), row.get("dep_type",""), str(row.get("depth","")))
        console.print(table)
    else:
        if stamp:
            print(stamp)
        print(f"Dependencies of '{file_path}':")
        for row in rows:
            print(f"  {row.get('dependency','')} ({row.get('dep_type','')}) [depth {row.get('depth','')}]")


def run_styles(element_name: str, project: str, rich: bool = False) -> None:
    """Show every CSS selector that styles element_name."""
    client = get_client(project)
    try:
        rows = client.find_styles(element_name, project)
        updated_at = _file_updated_at_for_entity(client, element_name, project)
    finally:
        client.close()

    if not rows:
        print(f"No CSS selectors found for '{element_name}'.")
        return

    stamp = _staleness_line(updated_at, rich_mode=rich)
    if rich:
        console.print(f"\n[bold blue]CSS rules targeting:[/] {element_name}\n")
        if stamp:
            console.print(stamp)
        table = _make_table(title=f"Selectors styling '{element_name}'", columns=["Selector", "Source File", "Line"])
        for row in rows:
            table.add_row(row.get("selector",""), row.get("source_file",""), str(row.get("line","")))
        console.print(table)
    else:
        if stamp:
            print(stamp)
        print(f"CSS selectors for '{element_name}':")
        for row in rows:
            print(f"  {row.get('selector','')} in {row.get('source_file','')} line {row.get('line','')}")


def run_trace(start_name: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Trace the call chain forward from start_name."""
    client = get_client(project)
    try:
        rows = client.trace_calls(start_name, project, max_hops)
        updated_at = _file_updated_at_for_entity(client, start_name, project)
    finally:
        client.close()

    if not rows:
        print(f"'{start_name}' makes no tracked calls within {max_hops} hops.")
        return

    stamp = _staleness_line(updated_at, rich_mode=rich)
    if rich:
        console.print(f"\n[bold blue]Call trace from:[/] {start_name}\n")
        if stamp:
            console.print(stamp)
        table = _make_table(title=f"Call chain from '{start_name}'", columns=["Callee", "Type", "File", "Depth"])
        for row in rows:
            table.add_row(row.get("callee_name",""), row.get("callee_type",""), row.get("callee_file",""), str(row.get("depth","")))
        console.print(table)
    else:
        if stamp:
            print(stamp)
        print(f"Call chain from '{start_name}':")
        for row in rows:
            print(f"  {row.get('callee_name','')} ({row.get('callee_type','')}) in {row.get('callee_file','')} [depth {row.get('depth','')}]")


def run_tree(project: str, rich: bool = False) -> None:
    """Print the full project hierarchy as a tree."""
    client = get_client(project)
    try:
        rows = client.get_project_tree(project)
        last_ingested = client.get_project_last_ingested(project)
    finally:
        client.close()

    if not rows:
        print(f"No hierarchy found for project '{project}'. Has it been ingested?")
        return

    stamp = _staleness_line(last_ingested, rich_mode=rich)
    if rich:
        console.print(f"\n[bold blue]Hierarchy for project:[/] {project}\n")
        if stamp:
            console.print(stamp)
        rich_tree = Tree(f"[bold cyan]{project}[/]")
        path_to_node: dict[str, Tree] = {}
        for row in rows:
            path = row.get("path") or row.get("name", "")
            name = row.get("name", path)
            node_type = row.get("node_type", "")
            label = _node_label(node_type, name)
            parts = [p for p in path.replace("\\", "/").split("/") if p]
            parent_path = "/".join(parts[:-1])
            parent_node = path_to_node.get(parent_path, rich_tree)
            child_node = parent_node.add(label)
            path_to_node[path] = child_node
        console.print(rich_tree)
    else:
        if stamp:
            print(stamp)
        print(f"Project tree: {project}")
        for row in rows:
            path = row.get("path") or row.get("name", "")
            depth = len([p for p in path.replace("\\", "/").split("/") if p]) - 1
            print(f"{'  ' * depth}{row.get('node_type','')}: {row.get('name','')}")


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def _check_neo4j(project: str) -> None:
    """Fail fast with a helpful message if Neo4j is unreachable or auth fails."""
    client = get_client(project)
    try:
        client._run_read("RETURN 1")
        client.close()
    except Exception as e:
        client.close()
        msg = str(e)
        ename = type(e).__name__
        if any(k in ename or k in msg for k in ("ServiceUnavailable", "ConnectionRefused", "refused", "timed out")):
            print("ERROR: Cannot connect to Neo4j at bolt://localhost:7687")
            print("  Start it:  docker compose up -d   (from graphrag/)")
            print("  Then wait ~5s and retry.")
        elif any(k in ename or k in msg for k in ("AuthError", "Unauthorized", "authentication")):
            print("ERROR: Neo4j authentication failed.")
            print("  Check NEO4J_USER and NEO4J_PASSWORD in your .env file.")
        else:
            print(f"ERROR: Neo4j connection failed — {ename}: {msg}")
        sys.exit(1)


def _check_watcher(project: str) -> None:
    """Warn (but don't exit) if no watcher process is running for this project."""
    import os
    pid_file = pid_file_path(project)
    if not os.path.exists(pid_file):
        print(f"WARNING: Watcher is not running for project '{project}'.")
        print(f"  Files edited outside this session won't be re-indexed automatically.")
        print(f"  Start it:  python main.py watch <repo_path> --project {project}")
        return
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # signal 0 checks if the process is alive without killing it
    except (ProcessLookupError, ValueError, OSError):
        try:
            os.unlink(pid_file)
        except OSError:
            pass
        print(f"WARNING: Watcher for project '{project}' is no longer running (stale PID file removed).")
        print(f"  Start it:  python main.py watch <repo_path> --project {project}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _staleness_line(timestamp: str | None, rich_mode: bool = False) -> str | None:
    """Return a staleness header line, with a warning if the index is older than STALE_WARN_HOURS."""
    if not timestamp:
        return None
    try:
        ts = datetime.fromisoformat(timestamp)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age_h > STALE_WARN_HOURS:
            warn = f"  WARNING: {age_h:.0f}h old — re-run: python main.py ingest-code . --project <name>"
            if rich_mode:
                return f"[yellow]# index updated: {timestamp}{warn}[/]"
            return f"# index updated: {timestamp}{warn}"
        if rich_mode:
            return f"[dim]# index updated: {timestamp}[/]"
        return f"# index updated: {timestamp}"
    except (ValueError, TypeError):
        return f"# index updated: {timestamp}"


def _file_updated_at_for_entity(client, entity_name: str, project: str) -> str | None:
    """Look up the updated_at timestamp of the file containing entity_name."""
    rows = client._run_read("""
        MATCH (e:Entity {project: $project})
        WHERE e.name = $name
        MATCH (f:File {path: e.file, project: $project})
        RETURN f.updated_at AS updated_at
        LIMIT 1
    """, project=project, name=entity_name)
    return rows[0]["updated_at"] if rows else None


def _make_table(title: str, columns: list[str]) -> Table:
    table = Table(title=title, show_lines=True, border_style="dim")
    for col in columns:
        table.add_column(col, style="cyan" if col in ("Caller", "Module", "Selector", "Callee") else "")
    return table


def _node_label(node_type: str, name: str) -> str:
    icons = {"Project": "📦", "Folder": "📁", "File": "📄", "Entity": "⚙"}
    icon = icons.get(node_type, "•")
    colour = {"File": "green", "Folder": "blue", "Entity": "yellow"}.get(node_type, "white")
    return f"[{colour}]{icon} {name}[/]"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Code-aware graph traversal CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--project", default="default",
                        help="Project name to query (default: 'default')")
    parser.add_argument("--hops", type=int, default=DEFAULT_HOPS,
                        help=f"Max traversal depth (default: {DEFAULT_HOPS})")
    parser.add_argument("--impact", metavar="ENTITY",
                        help="What calls ENTITY? (reverse CALLS traversal)")
    parser.add_argument("--deps", metavar="FILE",
                        help="What does FILE import? (forward IMPORTS traversal)")
    parser.add_argument("--styles", metavar="ELEMENT",
                        help="What CSS selectors style ELEMENT?")
    parser.add_argument("--trace", metavar="ENTITY",
                        help="Trace forward call chain from ENTITY")
    parser.add_argument("--tree", metavar="PROJECT",
                        help="Print full folder/file hierarchy for PROJECT")
    parser.add_argument("--rich", action="store_true",
                        help="Rich formatted output with tables and colour (default: plain text)")
    parser.add_argument("--list-projects", action="store_true",
                        help="List all ingested projects")
    return parser.parse_args()


if __name__ == "__main__":
    main()
