"""Data-fetch helpers over the local code knowledge graph.

Structured query functions (fetch_*) shared by the MCP server. There is no CLI
here — agents query the graph through the codecompass MCP tools.
"""

from __future__ import annotations

from contextlib import closing
import json
import xml.etree.ElementTree as ET

from graph.code_graph_client import get_client

DEFAULT_HOPS = 3


# ---------------------------------------------------------------------------
# Data-fetch helpers (used by CLI and MCP server)
# ---------------------------------------------------------------------------

def fetch_impact(entity_name: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS) -> dict:
    """Return callers of entity_name as structured data."""
    with closing(get_client(repo_path)) as client:
        rows = client.find_callers(entity_name, project, max_hops)
        updated_at = _entity_updated_at(client, entity_name)
    return {"entity": entity_name, "callers": rows, "updated_at": updated_at}


def fetch_grep(pattern: str, repo_path: str, project: str, field: str = "all",
               ignore_case: bool = True, limit: int = 100) -> dict:
    """Regex-search the graph — 'grep' over indexed entities, not file lines."""
    with closing(get_client(repo_path)) as client:
        return client.grep_graph(pattern, project, field=field,
                                 ignore_case=ignore_case, limit=limit)


def fetch_deps(file_path: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS) -> dict:
    """Return what file_path imports as structured data."""
    with closing(get_client(repo_path)) as client:
        rows = client.find_dependencies(file_path, project, max_hops)
        updated_at = client.get_file_updated_at(file_path, project)
    return {"file": file_path, "dependencies": rows, "updated_at": updated_at}


def fetch_styles(element_name: str, repo_path: str, project: str) -> dict:
    """Return CSS selectors that style element_name as structured data."""
    with closing(get_client(repo_path)) as client:
        rows = client.find_styles(element_name, project)
        updated_at = _entity_updated_at(client, element_name)
    return {"element": element_name, "selectors": rows, "updated_at": updated_at}


def fetch_trace(start_name: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS) -> dict:
    """Return forward call chain from start_name as structured data."""
    with closing(get_client(repo_path)) as client:
        rows = client.trace_calls(start_name, project, max_hops)
        updated_at = _entity_updated_at(client, start_name)
    return {"entity": start_name, "calls": rows, "updated_at": updated_at}


def fetch_blast_radius(target: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS) -> dict:
    """Return blast radius of target as structured data."""
    with closing(get_client(repo_path)) as client:
        rows, target_file = client.get_blast_radius(target, project, max_hops)
        updated_at = client.get_file_updated_at(target_file, project) if target_file else None

    if target_file is None:
        return {"target": target, "found": False, "files": [], "updated_at": None}

    seen: dict[str, dict] = {}
    for row in rows:
        f = row["file"]
        if f not in seen or row["hops"] < seen[f]["hops"]:
            seen[f] = row

    if target_file not in seen:
        seen[target_file] = {"file": target_file, "edge_type": "self", "hops": 0}

    deduped = sorted(seen.values(), key=lambda r: (r["hops"], r["file"]))
    return {
        "target": target,
        "target_file": target_file,
        "found": True,
        "files": deduped,
        "updated_at": updated_at,
    }


def fetch_batch_impact(targets: list[str], repo_path: str, project: str, max_hops: int = DEFAULT_HOPS) -> dict:
    """Return union of blast radii across multiple targets as structured data."""
    flat_targets: list[str] = []
    for t in targets:
        flat_targets.extend(s.strip() for s in t.split(",") if s.strip())

    with closing(get_client(repo_path)) as client:
        merged: dict[str, dict] = {}
        resolved: list[str] = []
        staleness_ts: str | None = None

        for target in flat_targets:
            rows, target_file = client.get_blast_radius(target, project, max_hops)
            if target_file is None:
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

    deduped = sorted(
        [{"file": f, "hops": v["hops"], "via": sorted(v["via"])} for f, v in merged.items()],
        key=lambda r: (r["hops"], r["file"]),
    )
    return {
        "targets": flat_targets,
        "resolved": resolved,
        "not_found": [t for t in flat_targets if t not in resolved],
        "files": deduped,
        "updated_at": staleness_ts,
    }


def fetch_dead_code(repo_path: str, project: str, show_entrypoints: bool = False) -> dict:
    """Return dead-code candidates as structured data."""
    with closing(get_client(repo_path)) as client:
        result = client.find_dead_code(project)
    return {
        "project": project,
        "dead": result["dead"],
        "maybe_entrypoint": result["maybe_entrypoint"] if show_entrypoints else [],
        "show_entrypoints": show_entrypoints,
    }


def fetch_tree(repo_path: str, project: str) -> dict:
    """Return project hierarchy as structured data."""
    with closing(get_client(repo_path)) as client:
        rows = client.get_project_tree(project)
        last_ingested = client.get_project_last_ingested(project)
    return {"project": project, "tree": rows, "last_ingested": last_ingested}


def fetch_flow(start_name: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS,
               include_external: bool = False) -> dict:
    """Lean flow trace for an agent: just the call structure it needs to navigate.

    Returns each node's name/kind/file/depth and each edge's from/to/type/order/
    line — NO embedded source, docstrings, narration, or rendered image. Use
    fetch_flow_summary for a human-facing walkthrough (mermaid + narration).
    """
    with closing(get_client(repo_path)) as client:
        data = client.trace_flow(start_name, project, max_hops, include_external=include_external)

    nodes = data["nodes"]
    edges = data["edges"]
    if not nodes:
        return {"found": False, "entry_point": start_name, "nodes": [], "edges": []}

    edges = _order_edges(edges, project, start_name)
    lean_nodes = [
        {"id": n["id"], "name": n["name"], "kind": n.get("kind", ""),
         "file": n.get("file", ""), "line": n.get("line"), "depth": n["depth"]}
        for n in sorted(nodes, key=lambda n: n["depth"])
    ]
    lean_edges = [
        {"from": e["from"], "to": e["to"], "type": e["type"],
         "order": e.get("order"), "line": e.get("line")}
        for e in edges
    ]
    return {
        "found": True,
        "entry_point": start_name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": lean_nodes,
        "edges": lean_edges,
    }


def fetch_flow_summary(start_name: str, repo_path: str, project: str, max_hops: int = DEFAULT_HOPS,
                       include_external: bool = False, fmt: str = "mermaid") -> dict:
    """Human-facing flow walkthrough: the trace plus a rendered narration.

    Default format is "mermaid" (a Markdown flowchart + prose narration). "json"
    additionally embeds each function's signature, docstring, and source snippet;
    "drawio" renders a diagram. Heavier than fetch_flow — use when a person needs
    to read the flow, not when an agent just needs the structure.
    """
    with closing(get_client(repo_path)) as client:
        data = client.trace_flow(start_name, project, max_hops, include_external=include_external)

    nodes = data["nodes"]
    edges = data["edges"]
    if not nodes:
        return {"found": False, "entry_point": start_name, "nodes": [], "edges": [], "content": ""}

    edges = _order_edges(edges, project, start_name)
    if fmt == "json":
        content = json.dumps(_build_flow_json(nodes, edges, project, start_name, repo_path), indent=2)
    elif fmt == "drawio":
        content = _build_drawio(nodes, edges, project, start_name)
    else:
        fmt = "mermaid"
        content = _build_mermaid(nodes, edges, project, start_name)

    return {
        "found": True,
        "entry_point": start_name,
        "format": fmt,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "content": content,
    }


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


