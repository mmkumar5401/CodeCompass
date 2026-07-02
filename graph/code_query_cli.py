"""Code-aware traversal CLI for the local code knowledge graph.

    python -m graph.code_query_cli --impact "login()" <repo_path>
    python -m graph.code_query_cli --deps src/auth/login.py <repo_path>
    python -m graph.code_query_cli --styles LoginForm <repo_path>
    python -m graph.code_query_cli --trace "main()" <repo_path>
    python -m graph.code_query_cli --tree <repo_path>

Output is plain text by default (agent-friendly). Pass --rich for formatted tables.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
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
    repo_path = os.path.abspath(args.repo_path)
    project = os.path.basename(repo_path)

    if not os.path.exists(os.path.join(repo_path, ".codecompass")):
        print(f"ERROR: '{repo_path}' has not been initialized.")
        print(f"  Run: codecompass init {repo_path}")
        sys.exit(1)

    _check_watcher(project)

    if args.blast_radius:
        run_blast_radius(args.blast_radius, repo_path, project, max_hops=args.hops, rich=rich)
    elif args.batch_impact:
        run_batch_impact(args.batch_impact, repo_path, project, max_hops=args.hops, rich=rich)
    elif args.impact:
        run_impact(args.impact, repo_path, project, max_hops=args.hops, rich=rich)
    elif args.deps:
        run_deps(args.deps, repo_path, project, max_hops=args.hops, rich=rich)
    elif args.styles:
        run_styles(args.styles, repo_path, project, rich=rich)
    elif args.trace:
        run_trace(args.trace, repo_path, project, max_hops=args.hops, rich=rich)
    elif args.flow:
        run_flow(args.flow, repo_path, project, max_hops=args.hops, rich=rich,
                 output=args.flow_output, include_external=args.include_external,
                 fmt=args.format)
    elif args.dead_code:
        run_dead_code(repo_path, project, rich=rich, show_entrypoints=args.include_entrypoints)
    elif args.tree:
        run_tree(repo_path, project, rich=rich)
    else:
        print("No query mode specified. Use --help.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Query modes
# ---------------------------------------------------------------------------

def run_impact(entity_name: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Show what would break if entity_name is changed (reverse CALLS traversal)."""
    client = get_client(repo_path)
    try:
        rows = client.find_callers(entity_name, project, max_hops)
        updated_at = _entity_updated_at(client, entity_name)
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


def run_deps(file_path: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Show what a file imports, directly and transitively."""
    client = get_client(repo_path)
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


def run_styles(element_name: str, repo_path: str, project: str, rich: bool = False) -> None:
    """Show every CSS selector that styles element_name."""
    client = get_client(repo_path)
    try:
        rows = client.find_styles(element_name, project)
        updated_at = _entity_updated_at(client, element_name)
    finally:
        client.close()

    if not rows:
        print(f"No CSS selectors found for '{element_name}'.")
        return

    stamp = _staleness_line(updated_at, rich_mode=rich)
    if rich:
        console.print(f"\n[bold blue]CSS rules targeting:[/] {element_name}")
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


def run_trace(start_name: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Trace the call chain forward from start_name."""
    client = get_client(repo_path)
    try:
        rows = client.trace_calls(start_name, project, max_hops)
        updated_at = _entity_updated_at(client, start_name)
    finally:
        client.close()

    if not rows:
        print(f"'{start_name}' makes no tracked calls within {max_hops} hops.")
        return

    stamp = _staleness_line(updated_at, rich_mode=rich)
    if rich:
        console.print(f"\n[bold blue]Call trace from:[/] {start_name}")
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


def run_blast_radius(target: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Show every file reachable from target via CALLS/IMPORTS/INHERITS."""
    client = get_client(repo_path)
    try:
        rows, target_file = client.get_blast_radius(target, project, max_hops)
        updated_at = client.get_file_updated_at(target_file, project) if target_file else None
    finally:
        client.close()

    if target_file is None:
        print(f"ERROR: '{target}' not found in project '{project}'")
        sys.exit(1)

    seen: dict[str, dict] = {}
    for row in rows:
        f = row["file"]
        if f not in seen or row["hops"] < seen[f]["hops"]:
            seen[f] = row

    if target_file not in seen:
        seen[target_file] = {"file": target_file, "edge_type": "self", "hops": 0}

    deduped = sorted(seen.values(), key=lambda r: (r["hops"], r["file"]))
    max_hop_seen = max(r["hops"] for r in deduped)
    summary = f"# blast radius: {len(deduped)} files across {max_hop_seen} hops"

    stamp = _staleness_line(updated_at, rich_mode=rich)
    if rich:
        if stamp:
            console.print(stamp)
        table = _make_table(title=f"Blast radius of '{target}'", columns=["File", "Relationship", "Hops"])
        for row in deduped:
            table.add_row(row["file"], row.get("edge_type",""), str(row["hops"]))
        console.print(table)
        console.print(f"[dim]{summary}[/]")
    else:
        if stamp:
            print(stamp)
        for row in deduped:
            print(row["file"])
        print(summary)


def run_batch_impact(targets: list[str], repo_path: str, project: str, max_hops: int = DEFAULT_HOPS, rich: bool = False) -> None:
    """Union of blast radii across multiple targets."""
    flat_targets: list[str] = []
    for t in targets:
        flat_targets.extend(s.strip() for s in t.split(",") if s.strip())

    input_set = set(flat_targets)
    client = get_client(repo_path)
    try:
        merged: dict[str, dict] = {}
        resolved: list[str] = []
        staleness_ts: str | None = None

        for target in flat_targets:
            rows, target_file = client.get_blast_radius(target, project, max_hops)
            if target_file is None:
                print(f"WARNING: '{target}' not found in project '{project}'")
                continue
            resolved.append(target)
            if staleness_ts is None:
                staleness_ts = client.get_file_updated_at(target_file, project)

            all_rows = list(rows)
            if not any(r["file"] == target_file for r in all_rows):
                all_rows.append({"file": target_file, "edge_type": "self", "hops": 0})

            for row in all_rows:
                f = row["file"]
                h = row["hops"]
                if f not in merged:
                    merged[f] = {"hops": h, "via": {target}}
                else:
                    if h < merged[f]["hops"]:
                        merged[f]["hops"] = h
                    merged[f]["via"].add(target)
    finally:
        client.close()

    if not resolved:
        sys.exit(1)

    deduped = sorted(merged.items(), key=lambda kv: (kv[1]["hops"], kv[0]))
    max_hop_seen = max(v["hops"] for _, v in deduped) if deduped else 0
    summary = f"# batch impact: {len(deduped)} files, {len(flat_targets)} input targets, {max_hop_seen} hops"

    stamp = _staleness_line(staleness_ts, rich_mode=rich)
    if rich:
        if stamp:
            console.print(stamp)
        table = _make_table(title=f"Batch impact ({len(targets)} targets)", columns=["File", "Via", "Hops"])
        for f, meta in deduped:
            flags = " [also in input]" if f in input_set else ""
            table.add_row(f"{f}{flags}", ", ".join(sorted(meta["via"])), str(meta["hops"]))
        console.print(table)
        console.print(f"[dim]{summary}[/]")
    else:
        if stamp:
            print(stamp)
        for f, meta in deduped:
            flags = "  [also in input]" if f in input_set else ""
            print(f"{f}  [via: {', '.join(sorted(meta['via']))}]{flags}")
        print(summary)


def run_dead_code(repo_path: str, project: str, rich: bool = False,
                  show_entrypoints: bool = False) -> None:
    """Report entities with no inbound caller/importer — candidates for removal."""
    client = get_client(repo_path)
    try:
        result = client.find_dead_code(project)
    finally:
        client.close()

    dead = result["dead"]
    maybe = result["maybe_entrypoint"]

    if not dead and not maybe:
        print("No dead-code candidates found — every entity has an inbound reference.")
        return

    def fmt(rows: list[dict]) -> None:
        by_file: dict[str, list[dict]] = {}
        for r in rows:
            by_file.setdefault(r["file"], []).append(r)
        for f in sorted(by_file):
            if rich:
                console.print(f"  [dim]{f}[/]")
            else:
                print(f"  {f}")
            for r in by_file[f]:
                et = r.get("entity_type", "")
                if rich:
                    console.print(f"    [yellow]{r['name']}[/] [dim]({et})[/]")
                else:
                    print(f"    {r['name']} ({et})")

    header = "[bold red]Dead-code candidates[/]" if rich else "Dead-code candidates"
    if rich:
        console.print(f"\n{header} for {project}\n")
    else:
        print(f"\n{header} for {project}\n")

    print(f"Likely dead ({len(dead)}) — no caller or importer found:")
    fmt(dead)

    if show_entrypoints:
        print(f"\nPossible entry points ({len(maybe)}) — no static caller, but may be "
              "invoked via CLI dispatch, a registry, or a framework:")
        fmt(maybe)
    else:
        print(f"\n({len(maybe)} likely entry points hidden — pass --include-entrypoints to show)")

    print("\nNOTE: static analysis only. Dynamic dispatch, reflection, and "
          "string-based invocation are invisible. VERIFY (grep the name across "
          "the repo) before removing anything.")


def run_tree(repo_path: str, project: str, rich: bool = False) -> None:
    """Print the full project hierarchy as a tree."""
    client = get_client(repo_path)
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


_FLOW_EXT = {"drawio": ".drawio", "mermaid": ".md", "json": ".json"}


def run_flow(start_name: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS,
             rich: bool = False, output: str | None = None,
             include_external: bool = False, fmt: str = "drawio") -> None:
    """Generate a flow trace from a forward call/import traversal.

    Formats:
      drawio  - mxGraph XML for draw.io (default)
      mermaid - Markdown with an embedded mermaid flowchart
      json    - structured trace enriched with signatures, docstrings, and
                source snippets so an agent can narrate the data flow
    """
    client = get_client(repo_path)
    try:
        data = client.trace_flow(start_name, project, max_hops,
                                 include_external=include_external)
    finally:
        client.close()

    nodes = data["nodes"]
    edges = data["edges"]

    if not nodes:
        print(f"No flow found from '{start_name}' within {max_hops} hops.")
        sys.exit(1)

    # Number edges with a single global sequence in execution order (DFS from
    # the entry point), so each edge has a unique step: 1, then 2, then 3 ...
    edges = _order_edges(edges, project, start_name)

    if fmt == "json":
        payload = _build_flow_json(nodes, edges, project, start_name, repo_path)
        content = json.dumps(payload, indent=2)
    elif fmt == "mermaid":
        content = _build_mermaid(nodes, edges, project, start_name)
    else:
        content = _build_drawio(nodes, edges, project, start_name)

    if output is None:
        safe_name = start_name.replace("/", "_").replace(".", "_").replace(" ", "_")
        output = os.path.join(repo_path, ".codecompass",
                              f"flow_{safe_name}{_FLOW_EXT[fmt]}")

    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w") as f:
        f.write(content)

    print(f"Flow ({fmt}) written to {output}")
    print(f"  {len(nodes)} nodes, {len(edges)} edges")
    if fmt == "drawio":
        print("  Open in draw.io (desktop or https://app.diagrams.net)")
    elif fmt == "json":
        print("  JSON includes signatures, docstrings, and source snippets for narration.")

    if rich:
        console.print(f"\n[bold blue]Flow from:[/] {start_name}")
        for node in sorted(nodes, key=lambda n: n["depth"]):
            indent = "  " * node["depth"]
            console.print(f"{indent}[cyan]{node['name']}[/] [dim]({node['kind']})[/]")
    else:
        print(f"\nFlow from '{start_name}':")
        for node in sorted(nodes, key=lambda n: n["depth"]):
            indent = "  " * node["depth"]
            print(f"{indent}{node['name']} ({node['kind']})")


def _order_edges(edges: list[dict], project: str, start_name: str) -> list[dict]:
    """Assign each edge a unique global order via DFS from the entry point,
    visiting each caller's outgoing edges sorted by source line. The result is a
    strict 1..N sequence (no two edges share a number)."""
    from collections import defaultdict
    by_parent: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        by_parent[e["from"]].append(e)
    for group in by_parent.values():
        group.sort(key=lambda e: (e.get("line") or 0))

    start_id = f"{project}:{start_name.lower()}"
    if start_id not in by_parent and not any(
        e["to"] == start_id for e in edges
    ):
        start_id = edges[0]["from"] if edges else start_id

    ordered: list[dict] = []
    counter = 1
    visited_edges: set[int] = set()
    visited_nodes: set[str] = set()
    stack = [start_id]
    while stack:
        nid = stack.pop()
        if nid in visited_nodes:
            continue
        visited_nodes.add(nid)
        # Push children in reverse so the lowest-line edge is processed first.
        for e in reversed(by_parent.get(nid, [])):
            stack.append(e["to"])
    # Re-walk in forward order to number edges as execution reaches them.
    visited_nodes.clear()
    stack = [start_id]
    while stack:
        nid = stack.pop()
        if nid in visited_nodes:
            continue
        visited_nodes.add(nid)
        for e in by_parent.get(nid, []):
            if id(e) not in visited_edges:
                e2 = dict(e)
                e2["order"] = counter
                counter += 1
                ordered.append(e2)
                visited_edges.add(id(e))
        for e in reversed(by_parent.get(nid, [])):
            stack.append(e["to"])
    # Include any edges not reached by the DFS (defensive), preserving them.
    seen_pairs = {(e["from"], e["to"], e.get("line")) for e in ordered}
    for e in edges:
        if (e["from"], e["to"], e.get("line")) not in seen_pairs:
            e2 = dict(e)
            e2["order"] = counter
            counter += 1
            ordered.append(e2)
    return ordered


def _build_flow_json(nodes: list[dict], edges: list[dict], project: str,
                     start_name: str, repo_path: str) -> dict:
    """Enrich the flow trace with real code context for agent narration."""
    from ingestion.source_context import extract_entity_context

    enriched = []
    for n in sorted(nodes, key=lambda n: n["depth"]):
        ctx = extract_entity_context(repo_path, n.get("file", ""), n["name"])
        enriched.append({
            "id": n["id"],
            "name": n["name"],
            "kind": n["kind"],
            "file": n.get("file", ""),
            "depth": n["depth"],
            "signature": ctx["signature"],
            "docstring": ctx["docstring"],
            "start_line": ctx["start_line"],
            "end_line": ctx["end_line"],
            "source": ctx["snippet"],
        })

    return {
        "entry_point": start_name,
        "project": project,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": enriched,
        "edges": [
            {
                "from": e["from"],
                "to": e["to"],
                "type": e["type"],
                "order": e.get("order"),
                "call_site_file": e.get("file", ""),
                "call_site_line": e.get("line"),
            }
            for e in edges
        ],
        "narration_guide": (
            "Each node carries its real signature, docstring, and source snippet. "
            "The 'order' field on each edge is a unique global step number (1, 2, "
            "3 ...) giving the sequence in which calls happen. Use signatures + "
            "docstrings to describe what "
            "data enters and leaves each function, and the source snippet to explain "
            "the transformation. Narrate the flow from the entry point downward."
        ),
    }


def _execution_order(nodes: list[dict], edges: list[dict], project: str,
                     start_name: str) -> dict[str, int]:
    """DFS from the entry point, following each caller's call order, to assign a
    global 1-based execution step to every reachable node."""
    from collections import defaultdict
    children: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        children[e["from"]].append(e)
    for group in children.values():
        group.sort(key=lambda e: (e.get("order") or 0, e.get("line") or 0))

    start_id = f"{project}:{start_name.lower()}"
    if not any(n["id"] == start_id for n in nodes):
        start_id = next((n["id"] for n in nodes if n.get("depth") == 0), None)

    order: dict[str, int] = {}
    counter = 1
    stack = [start_id] if start_id else []
    while stack:
        nid = stack.pop()
        if nid is None or nid in order:
            continue
        order[nid] = counter
        counter += 1
        for e in reversed(children.get(nid, [])):
            if e["to"] not in order:
                stack.append(e["to"])
    return order


def _build_mermaid(nodes: list[dict], edges: list[dict], project: str,
                   start_name: str) -> str:
    """Build a Markdown file with an embedded numbered mermaid flowchart."""
    def safe(node_id: str) -> str:
        base = node_id.split(":", 1)[-1]
        return "n_" + "".join(c if c.isalnum() else "_" for c in base)

    step_order = _execution_order(nodes, edges, project, start_name)
    nodes_in_order = sorted(nodes, key=lambda n: step_order.get(n["id"], 1_000_000))

    lines = ["flowchart TD"]
    for n in nodes_in_order:
        nid = safe(n["id"])
        has_children = any(e["from"] == n["id"] for e in edges)
        if n["id"] == f"{project}:{start_name.lower()}":
            cls = "entryNode"
        elif has_children:
            cls = "fn"
        else:
            cls = "leafFn"
        label = n["name"].replace('"', "'")
        lines.append(f'    {nid}["{label}"]:::{cls}')
    for e in edges:
        f = safe(e["from"])
        t = safe(e["to"])
        if f != t:
            lines.append(f'    {f} -->|{e.get("order", "")}| {t}')

    # Invisible chain in execution-step order forces a strict top-to-bottom
    # layout (1 above 2 above 3 ...); real call edges remain as cross-links.
    seq = [safe(n["id"]) for n in nodes_in_order if n["id"] in step_order]
    for a, b in zip(seq, seq[1:]):
        lines.append(f"    {a} ~~~ {b}")

    lines.append("    classDef entryNode fill:#FFD54F,stroke:#B8860B,stroke-width:3px,color:#000;")
    lines.append("    classDef fn fill:#E3F2FD,stroke:#1976D2,color:#000;")
    lines.append("    classDef leafFn fill:#F3E5F5,stroke:#8E24AA,color:#000;")
    mmd = "\n".join(lines)

    return (
        f"# Flow: {start_name}\n\n"
        "Forward call/import trace from the CodeCompass graph. Arrows carry a "
        "unique global step number (1, 2, 3 ...) giving the order in which calls "
        "happen — follow them in sequence to read what runs first, second, third. "
        "Nodes are laid out top to bottom in that same execution order.\n\n"
        f"```mermaid\n{mmd}\n```\n"
    )


_EDGE_COLORS = {
    "CALLS": "#2196F3",
    "IMPORTS": "#4CAF50",
    "INHERITS": "#FF9800",
    "DEFINED_IN": "#9C27B0",
    "REFERENCES": "#607D8B",
}

_KIND_FILL = {
    "function": "#E3F2FD",
    "class": "#FFF3E0",
    "module": "#E8F5E9",
    "endpoint": "#FCE4EC",
    "variable": "#F3E5F5",
    "interface": "#FFF8E1",
    "trait": "#E0F7FA",
    "enum": "#EDE7F6",
    "property": "#FBE9E7",
    "constant": "#F1F8E9",
}


def _build_drawio(nodes: list[dict], edges: list[dict], project: str, start_name: str) -> str:
    """Build mxGraph XML for draw.io from flow nodes and edges."""
    node_ids = {n["id"]: i + 2 for i, n in enumerate(nodes)}  # 0=root, 1=parent

    # Layout: arrange nodes by depth, spread horizontally
    depth_groups: dict[int, list[dict]] = {}
    for n in nodes:
        depth_groups.setdefault(n["depth"], []).append(n)

    positions: dict[str, tuple[int, int]] = {}
    y_offset = 40
    for depth in sorted(depth_groups):
        group = depth_groups[depth]
        x_start = 40
        for i, n in enumerate(group):
            positions[n["id"]] = (x_start + i * 260, y_offset + depth * 140)

    root = ET.Element("mxfile", host="app.diagrams.net", type="device")
    diagram = ET.SubElement(root, "diagram", name=f"Flow: {start_name}", id="flow")
    model = ET.SubElement(diagram, "mxGraphModel", dx="1200", dy="800",
                          grid="1", gridSize="10", guides="1", tooltips="1",
                          connect="1", arrows="1", fold="1", page="1",
                          pageScale="1", pageWidth="1600", pageHeight="1200")
    mx_root = ET.SubElement(model, "root")
    ET.SubElement(mx_root, "mxCell", id="0")
    ET.SubElement(mx_root, "mxCell", id="1", parent="0")

    for n in nodes:
        cell_id = str(node_ids[n["id"]])
        entity_type = n["kind"].split(":")[0] if ":" in n["kind"] else ""
        fill = _KIND_FILL.get(entity_type, "#FFFFFF")
        is_start = n["depth"] == 0
        border = "strokeWidth=3;" if is_start else ""
        label = f"{n['name']}\n{n['kind']}"
        x, y = positions.get(n["id"], (40, 40))

        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};"
                 f"strokeColor=#666666;{border}fontSize=12;")

        cell = ET.SubElement(mx_root, "mxCell", id=cell_id, value=label,
                             style=style, vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                      width="220", height="60", **{"as": "geometry"})

    edge_id = len(nodes) + 2
    for e in edges:
        src = node_ids.get(e["from"])
        tgt = node_ids.get(e["to"])
        if src is None or tgt is None:
            continue
        color = _EDGE_COLORS.get(e["type"], "#333333")
        style = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;"
                 f"jettySize=auto;html=1;strokeColor={color};strokeWidth=2;"
                 f"fontSize=11;")
        ET.SubElement(mx_root, "mxCell", id=str(edge_id), value=e["type"],
                      style=style, edge="1", parent="1",
                      source=str(src), target=str(tgt))
        edge_id += 1

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def _check_watcher(project: str) -> None:
    """Warn (but don't exit) if no watcher process is running for this project."""
    pid_file = pid_file_path(project)
    if not os.path.exists(pid_file):
        return  # Watcher is optional — silently skip
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError, OSError):
        try:
            os.unlink(pid_file)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity_updated_at(client, entity_name: str) -> str | None:
    """Look up the updated_at of the file containing an entity."""
    for n, attr in client.graph.nodes(data=True):
        if attr.get("type") == "Entity" and attr.get("name") == entity_name:
            file_path = attr.get("file")
            if file_path:
                for fn, fattr in client.graph.nodes(data=True):
                    if fattr.get("type") == "File" and fattr.get("path") == file_path:
                        return fattr.get("updated_at")
    return None


def _staleness_line(timestamp: str | None, rich_mode: bool = False) -> str | None:
    if not timestamp:
        return None
    try:
        ts = datetime.fromisoformat(timestamp)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        warn = f"  WARNING: {age_h:.0f}h old — re-run: codecompass ingest-code <repo_path>" if age_h > STALE_WARN_HOURS else ""
        if rich_mode:
            return f"[{'yellow' if warn else 'dim'}]# index updated: {timestamp}{warn}[/]"
        return f"# index updated: {timestamp}{warn}"
    except (ValueError, TypeError):
        return f"# index updated: {timestamp}"


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
    parser.add_argument("repo_path", nargs="?", default=".",
                        help="Path to the repository (default: current directory)")
    parser.add_argument("--hops", type=int, default=DEFAULT_HOPS)
    parser.add_argument("--blast-radius", metavar="TARGET")
    parser.add_argument("--batch-impact", metavar="TARGET", nargs="+")
    parser.add_argument("--impact", metavar="ENTITY")
    parser.add_argument("--deps", metavar="FILE")
    parser.add_argument("--styles", metavar="ELEMENT")
    parser.add_argument("--trace", metavar="ENTITY")
    parser.add_argument("--flow", metavar="ENTITY")
    parser.add_argument("--flow-output", metavar="PATH", default=None)
    parser.add_argument("--include-external", action="store_true",
                        help="Include external/stdlib symbols in --flow output")
    parser.add_argument("--format", choices=("drawio", "mermaid", "json"),
                        default="drawio",
                        help="Output format for --flow (default: drawio). "
                             "json includes signatures, docstrings, and source "
                             "snippets for agent narration.")
    parser.add_argument("--dead-code", action="store_true",
                        help="Find entities with no inbound caller/importer (candidates to remove)")
    parser.add_argument("--include-entrypoints", action="store_true",
                        help="Also list likely entry points (run_*, handlers, tests) in --dead-code")
    parser.add_argument("--tree", action="store_true")
    parser.add_argument("--rich", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
