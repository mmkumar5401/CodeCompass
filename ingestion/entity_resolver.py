import anthropic
import json
import re
from dotenv import load_dotenv

load_dotenv(override=True)
_client = anthropic.Anthropic()

CHUNK_SIZE = 80

RESOLVER_SYSTEM = """You are a knowledge graph entity resolver.

Given a list of entity names from a knowledge graph, identify groups of names that clearly refer to the SAME real-world entity or concept.

Rules:
- Be CONSERVATIVE — only group names you are highly confident are the same entity
- The first name in each group becomes the canonical (kept) name — pick the clearest, most complete form
- Do not group names that are merely related

Return ONLY valid JSON, no other text:
{"groups": [["canonical_name", "duplicate1", "duplicate2"], ...]}

If no clear duplicates exist, return {"groups": []}"""


def resolve_entities(client) -> int:
    """Identify and merge duplicate entity nodes in the local graph."""
    all_nodes = [
        {"id": n, "name": attr.get("name", n), "type": attr.get("entity_type", "")}
        for n, attr in client.graph.nodes(data=True)
        if attr.get("type") == "Entity"
    ]

    if len(all_nodes) < 2:
        print("[resolver] fewer than 2 nodes — nothing to resolve.")
        return 0

    print(f"[resolver] scanning {len(all_nodes)} nodes for duplicates...", flush=True)
    all_groups: list[list[str]] = []

    for i in range(0, len(all_nodes), CHUNK_SIZE):
        chunk = all_nodes[i: i + CHUNK_SIZE]
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
            groups = [g for g in groups if isinstance(g, list) and len(g) >= 2]
            if groups:
                print(f"  chunk {i // CHUNK_SIZE + 1}: found {len(groups)} duplicate group(s)", flush=True)
            all_groups.extend(groups)
        except (json.JSONDecodeError, IndexError) as e:
            print(f"  [resolver] parse error on chunk {i // CHUNK_SIZE + 1}: {e}")
            continue

    if not all_groups:
        print("[resolver] no duplicates found.")
        return 0

    name_to_node = {n["name"]: n for n in all_nodes}
    merged_count = 0

    for group in all_groups:
        canonical_name = group[0]
        canonical_node = name_to_node.get(canonical_name)
        if not canonical_node:
            continue

        for dup_name in group[1:]:
            dup_node = name_to_node.get(dup_name)
            if not dup_node or dup_node["id"] == canonical_node["id"]:
                continue
            print(f"  '{dup_name}'  →  '{canonical_name}'")
            # Remap all edges from duplicate to canonical
            dup_id = dup_node["id"]
            canon_id = canonical_node["id"]
            for pred in list(client.graph.predecessors(dup_id)):
                for key, data in list(client.graph.get_edge_data(pred, dup_id).items()):
                    client.graph.add_edge(pred, canon_id, **data)
            for succ in list(client.graph.successors(dup_id)):
                for key, data in list(client.graph.get_edge_data(dup_id, succ).items()):
                    client.graph.add_edge(canon_id, succ, **data)
            client.graph.remove_node(dup_id)
            merged_count += 1

    if merged_count:
        client.save()

    return merged_count
