"""Code-aware traversal CLI for the code knowledge graph.

Extends the document query_cli with code-specific traversal patterns:

    python -m graph.code_query_cli --impact "login()"
    python -m graph.code_query_cli --deps src/auth/login.py
    python -m graph.code_query_cli --styles LoginForm
    python -m graph.code_query_cli --trace "main()" --hops 4
    python -m graph.code_query_cli --tree frontend
    python -m graph.code_query_cli --cross-project frontend api-service
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python graph/code_query_cli.py` from the project root
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

import graph.db_router as db_router

console = Console()

# Default traversal depth for multi-hop queries
DEFAULT_HOPS = 3


def main() -> None:
    args = _parse_args()
    plain = args.plain

    if args.impact:
        run_impact(args.impact, args.project, max_hops=args.hops, plain=plain)
    elif args.deps:
        run_deps(args.deps, args.project, max_hops=args.hops, plain=plain)
    elif args.styles:
        run_styles(args.styles, args.project, plain=plain)
    elif args.trace:
        run_trace(args.trace, args.project, max_hops=args.hops, plain=plain)
    elif args.tree:
        run_tree(args.tree, plain=plain)
    elif args.cross_project:
        run_cross_project(args.cross_project[0], args.cross_project[1], plain=plain)
    else:
        console.print("[red]No query mode specified. Use --help.[/]")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Query modes
# ---------------------------------------------------------------------------

def run_impact(entity_name: str, project: str, max_hops: int = DEFAULT_HOPS, plain: bool = False) -> None:
    """Show what would break if entity_name is changed (reverse CALLS traversal)."""
    client = _project_client(project)
    try:
        rows = client.find_callers(entity_name, project, max_hops)
    finally:
        client.close()

    if not rows:
        print(f"Nothing calls '{entity_name}' within {max_hops} hops.")
        return

    if plain:
        print(f"Callers of '{entity_name}':")
        for row in rows:
            print(f"  {row.get('caller_name','')} ({row.get('caller_type','')}) in {row.get('caller_file','')} [depth {row.get('depth','')}]")
    else:
        console.print(f"\n[bold blue]Impact analysis:[/] {entity_name}\n")
        table = _make_table(title=f"Callers of '{entity_name}'", columns=["Caller", "Type", "File", "Depth"])
        for row in rows:
            table.add_row(row.get("caller_name",""), row.get("caller_type",""), row.get("caller_file",""), str(row.get("depth","")))
        console.print(table)


def run_deps(file_path: str, project: str, max_hops: int = DEFAULT_HOPS, plain: bool = False) -> None:
    """Show what a file imports, directly and transitively."""
    client = _project_client(project)
    try:
        rows = client.find_dependencies(file_path, project, max_hops)
    finally:
        client.close()

    if not rows:
        print(f"No imports found for '{file_path}'.")
        return

    if plain:
        print(f"Dependencies of '{file_path}':")
        for row in rows:
            print(f"  {row.get('dependency','')} ({row.get('dep_type','')}) [depth {row.get('depth','')}]")
    else:
        console.print(f"\n[bold blue]Dependencies of:[/] {file_path}\n")
        table = _make_table(title=f"Dependencies of '{file_path}'", columns=["Module", "Type", "Depth"])
        for row in rows:
            table.add_row(row.get("dependency",""), row.get("dep_type",""), str(row.get("depth","")))
        console.print(table)


def run_styles(element_name: str, project: str, plain: bool = False) -> None:
    """Show every CSS selector that styles element_name."""
    client = _project_client(project)
    try:
        rows = client.find_styles(element_name, project)
    finally:
        client.close()

    if not rows:
        print(f"No CSS selectors found for '{element_name}'.")
        return

    if plain:
        print(f"CSS selectors for '{element_name}':")
        for row in rows:
            print(f"  {row.get('selector','')} in {row.get('source_file','')} line {row.get('line','')}")
    else:
        console.print(f"\n[bold blue]CSS rules targeting:[/] {element_name}\n")
        table = _make_table(title=f"Selectors styling '{element_name}'", columns=["Selector", "Source File", "Line"])
        for row in rows:
            table.add_row(row.get("selector",""), row.get("source_file",""), str(row.get("line","")))
        console.print(table)


def run_trace(start_name: str, project: str, max_hops: int = DEFAULT_HOPS, plain: bool = False) -> None:
    """Trace the call chain forward from start_name."""
    client = _project_client(project)
    try:
        rows = client.trace_calls(start_name, project, max_hops)
    finally:
        client.close()

    if not rows:
        print(f"'{start_name}' makes no tracked calls within {max_hops} hops.")
        return

    if plain:
        print(f"Call chain from '{start_name}':")
        for row in rows:
            print(f"  {row.get('callee_name','')} ({row.get('callee_type','')}) in {row.get('callee_file','')} [depth {row.get('depth','')}]")
    else:
        console.print(f"\n[bold blue]Call trace from:[/] {start_name}\n")
        table = _make_table(title=f"Call chain from '{start_name}'", columns=["Callee", "Type", "File", "Depth"])
        for row in rows:
            table.add_row(row.get("callee_name",""), row.get("callee_type",""), row.get("callee_file",""), str(row.get("depth","")))
        console.print(table)


def run_tree(project: str, plain: bool = False) -> None:
    """Print the full project hierarchy as a rich tree."""
    client = _project_client(project)
    try:
        rows = client.get_project_tree(project)
    finally:
        client.close()

    if not rows:
        print(f"No hierarchy found for project '{project}'. Has it been ingested?")
        return

    if plain:
        print(f"Project tree: {project}")
        for row in rows:
            path = row.get("path") or row.get("name", "")
            depth = len([p for p in path.replace("\\", "/").split("/") if p]) - 1
            print(f"{'  ' * depth}{row.get('node_type','')}: {row.get('name','')}")
    else:
        console.print(f"\n[bold blue]Hierarchy for project:[/] {project}\n")
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


def run_cross_project(project_a: str, project_b: str, plain: bool = False) -> None:
    """Show BRIDGE edges between two projects via the master graph."""
    master = db_router.master_client()
    try:
        rows = master._run_read("""
            MATCH (a:Entity {project: $pa})-[br:BRIDGE]->(b:Entity {project: $pb})
            RETURN a.name AS entity_a, b.name AS entity_b,
                   br.type AS bridge_type, br.confidence AS confidence
            ORDER BY br.confidence DESC
        """, pa=project_a, pb=project_b)
    finally:
        master.close()

    if not rows:
        print(f"No bridge edges found between '{project_a}' and '{project_b}'.")
        return

    if plain:
        print(f"Bridges: {project_a} <-> {project_b}")
        for row in rows:
            print(f"  {row.get('entity_a','')} --[{row.get('bridge_type','')}]--> {row.get('entity_b','')} (confidence {row.get('confidence',0):.2f})")
    else:
        console.print(f"\n[bold blue]Cross-project bridges:[/] {project_a} ↔ {project_b}\n")
        table = _make_table(title=f"Bridges: {project_a} ↔ {project_b}", columns=[project_a, project_b, "Bridge Type", "Confidence"])
        for row in rows:
            table.add_row(row.get("entity_a",""), row.get("entity_b",""), row.get("bridge_type",""), f"{row.get('confidence',0):.2f}")
        console.print(table)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_client(project: str):
    return db_router.project_client(project)


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
    parser.add_argument("--cross-project", nargs=2, metavar=("PROJECT_A", "PROJECT_B"),
                        help="Show BRIDGE edges between two projects")
    parser.add_argument("--plain", action="store_true",
                        help="Plain text output (no rich formatting, fewer tokens)")
    return parser.parse_args()


if __name__ == "__main__":
    main()
