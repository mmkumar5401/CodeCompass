import anthropic
import json
import re
import subprocess
import sys
from dotenv import load_dotenv
from graph.neo4j_client import Neo4jClient

load_dotenv(override=True)
_client = anthropic.Anthropic()

# Chunk size: how many node names to show Haiku per pass.
# Larger = fewer API calls but risks missing cross-chunk duplicates.
CHUNK_SIZE = 80

RESOLVER_SYSTEM = """You are a knowledge graph entity resolver.

Given a list of entity names from a knowledge graph, identify groups of names that clearly refer to the SAME real-world entity or concept.

Examples of duplicates:
- "knowledge tracing" and "Knowledge Tracing System" (same concept, different verbosity)
- "BKT" and "Bayesian Knowledge Tracing" (acronym + full name)
- "student model" and "Student Model" (casing only)

Rules:
- Be CONSERVATIVE — only group names you are highly confident are the same entity
- The first name in each group becomes the canonical (kept) name — pick the clearest, most complete form
- Do not group names that are merely related (e.g. "Python" and "Python library" are NOT the same)

Return ONLY valid JSON, no other text:
{"groups": [["canonical_name", "duplicate1", "duplicate2"], ...]}

If no clear duplicates exist, return {"groups": []}"""


def resolve_entities(graph: Neo4jClient, dry_run: bool = False) -> int:
    """
    Identify and merge duplicate entity nodes in the graph.

    Strategy (Facade over Haiku + Neo4j):
      1. Fetch all node names
      2. Chunk into groups of CHUNK_SIZE and ask Haiku to find duplicates
      3. Collect all duplicate groups across chunks
      4. Merge each group: re-point relationships to canonical node, delete duplicates

    Returns the number of nodes merged (0 on dry_run).
    """
    all_nodes = graph.get_all_node_names()
    if len(all_nodes) < 2:
        print("[resolver] fewer than 2 nodes — nothing to resolve.")
        return 0

    print(f"[resolver] scanning {len(all_nodes)} nodes for duplicates...", flush=True)

    all_groups: list[list[str]] = []

    for i in range(0, len(all_nodes), CHUNK_SIZE):
        chunk = all_nodes[i : i + CHUNK_SIZE]
        node_list = "\n".join(f"- {n['name']} ({n['type']})" for n in chunk)

        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=RESOLVER_SYSTEM,
            messages=[{"role": "user", "content": f"Entity names to resolve:\n{node_list}"}],
        )

        try:
            raw = response.content[0].text.strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"```$", "", raw.strip(), flags=re.MULTILINE)
            groups = json.loads(raw).get("groups", [])
            # Filter out singleton or empty groups
            groups = [g for g in groups if isinstance(g, list) and len(g) >= 2]
            if groups:
                print(f"  chunk {i//CHUNK_SIZE + 1}: found {len(groups)} duplicate group(s)", flush=True)
            all_groups.extend(groups)
        except (json.JSONDecodeError, IndexError) as e:
            print(f"  [resolver] parse error on chunk {i//CHUNK_SIZE + 1}: {e}")
            continue

    if not all_groups:
        print("[resolver] no duplicates found.")
        return 0

    name_to_node = {n["name"]: n for n in all_nodes}
    merged_count = 0

    for group in all_groups:
        canonical_name = group[0]
        duplicates = group[1:]

        canonical_node = name_to_node.get(canonical_name)
        if not canonical_node:
            # Canonical name itself doesn't exist — skip
            continue

        dup_ids = []
        for dup_name in duplicates:
            dup_node = name_to_node.get(dup_name)
            if not dup_node:
                continue
            if dup_node["id"] == canonical_node["id"]:
                continue
            tag = "[dry-run] " if dry_run else ""
            print(f"  {tag}'{dup_name}'  →  '{canonical_name}'")
            dup_ids.append(dup_node["id"])

        if dup_ids and not dry_run:
            graph.merge_nodes(canonical_node["id"], canonical_name, dup_ids)
            merged_count += len(dup_ids)

    return merged_count


def resolve_dump(graph: Neo4jClient, out_file: str) -> None:
    """
    Phase 1 of native resolve: write all node names to a JSON file so that
    Claude Code can analyse them and produce a groups file.

    Usage:
        python main.py resolve --native --dump /tmp/nodes.json
        # → Claude Code reads /tmp/nodes.json, writes /tmp/groups.json
        python main.py resolve --native --apply /tmp/groups.json
    """
    all_nodes = graph.get_all_node_names()
    with open(out_file, "w") as f:
        json.dump(all_nodes, f, indent=2)
    print(f"[resolver] {len(all_nodes)} nodes written to: {out_file}")
    print()
    print("Next step — ask Claude Code:")
    print(f'  "Read {out_file}, find duplicate entity names, write groups to /tmp/resolve_groups.json"')
    print()
    print("Then apply:")
    print("  python main.py resolve --native --apply /tmp/resolve_groups.json")


def resolve_apply(graph: Neo4jClient, groups_file: str, dry_run: bool = False) -> int:
    """
    Phase 2 of native resolve: load a groups JSON file produced by Claude Code
    and merge the duplicates.

    groups.json format:
        [["canonical_name", "duplicate1", "duplicate2"], ...]
    """
    with open(groups_file) as f:
        all_groups = json.load(f)

    all_groups = [g for g in all_groups if isinstance(g, list) and len(g) >= 2]
    if not all_groups:
        print("[resolver] groups file is empty — nothing to merge.")
        return 0

    all_nodes = graph.get_all_node_names()
    name_to_node = {n["name"]: n for n in all_nodes}
    merged_count = 0

    for group in all_groups:
        canonical_name = group[0]
        duplicates = group[1:]
        canonical_node = name_to_node.get(canonical_name)
        if not canonical_node:
            print(f"  [skip] canonical not found: {canonical_name!r}")
            continue

        dup_ids = []
        for dup_name in duplicates:
            dup_node = name_to_node.get(dup_name)
            if not dup_node or dup_node["id"] == canonical_node["id"]:
                continue
            tag = "[dry-run] " if dry_run else ""
            print(f"  {tag}'{dup_name}'  →  '{canonical_name}'")
            dup_ids.append(dup_node["id"])

        if dup_ids and not dry_run:
            graph.merge_nodes(canonical_node["id"], canonical_name, dup_ids)
            merged_count += len(dup_ids)

    return merged_count
