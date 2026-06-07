import anthropic
import json
import re
from dotenv import load_dotenv
from graph.neo4j_client import Neo4jClient

load_dotenv(override=True)
_client = anthropic.Anthropic()

SEED_SYSTEM = """You are a graph search assistant. You are given a user query and a list of
nodes that exist in a knowledge graph. Select the nodes that are the best starting points
for answering the query.

Rules:
- Choose nodes whose names directly relate to the query's subject matter
- Return 2–5 nodes maximum — prefer fewer, highly relevant nodes over many loosely related ones
- Use ONLY names from the provided list — do not invent new ones
- Return ONLY valid JSON: {"seeds": ["Exact Node Name", ...]}"""


def find_seed_nodes(query: str, graph: Neo4jClient) -> list[dict]:
    """
    Ground seed selection in the actual graph vocabulary.

    Fetches all node names from Neo4j and asks Haiku to pick the most relevant
    ones for the query — eliminates hallucinated entity names from pure NER.
    """
    all_nodes = graph.get_all_node_names()
    if not all_nodes:
        return []

    node_list = "\n".join(f"- {n['name']} ({n['type']})" for n in all_nodes)
    prompt = f"Query: {query}\n\nAvailable graph nodes:\n{node_list}"

    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system=SEED_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```$", "", raw.strip(), flags=re.MULTILINE)
        selected_names: list[str] = json.loads(raw).get("seeds", [])
    except (json.JSONDecodeError, IndexError):
        selected_names = []

    # Exact-match selected names back to node dicts
    name_to_node = {n["name"]: n for n in all_nodes}
    seeds = [name_to_node[name] for name in selected_names if name in name_to_node]

    # Fallback: fuzzy match if LLM returned no valid names
    if not seeds:
        print("[seed_finder] no exact match — falling back to fuzzy search")
        seeds = graph.find_nodes_by_name(selected_names or [query[:50]])

    print(f"[seed_finder] selected {len(seeds)} seed node(s): {[n['name'] for n in seeds]}")
    return seeds
