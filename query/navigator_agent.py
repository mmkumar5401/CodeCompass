from dataclasses import dataclass
from tqdm import tqdm
from graph.neo4j_client import Neo4jClient
from query.seed_finder import find_seed_nodes
from query.relevance_filter import filter_relevant_neighbours
from models.types import TraversalStep

MAX_TOTAL_NODES = 150
MAX_CONSECUTIVE_MISSES = 2


@dataclass
class _FrontierNode:
    node_id: str
    node_name: str
    depth: int
    consecutive_misses: int = 0


def navigate(
    query: str, graph: Neo4jClient
) -> tuple[list[dict], list[TraversalStep], int]:
    """
    Branch-aware BFS traversal — one LLM call per BFS layer.

    Each BFS iteration fetches ALL frontier nodes' neighbours in a single Neo4j
    call, then scores them all in a single Haiku call. Per-branch consecutive
    miss counters are maintained using the from_id on each returned row.

    Returns (collected_nodes, traversal_steps, max_depth_reached).
    """
    seed_nodes = find_seed_nodes(query, graph)
    if not seed_nodes:
        return [], [], 0

    frontier: list[_FrontierNode] = [
        _FrontierNode(n["id"], n["name"], depth=0) for n in seed_nodes
    ]
    visited: set[str] = {n["id"] for n in seed_nodes}
    collected_nodes: list[dict] = list(seed_nodes)
    all_steps: list[TraversalStep] = []
    max_depth = 0

    with tqdm(total=MAX_TOTAL_NODES, desc="Traversing graph", unit="node", dynamic_ncols=True) as pbar:
        pbar.update(len(seed_nodes))

        while frontier and len(collected_nodes) < MAX_TOTAL_NODES:
            next_frontier: list[_FrontierNode] = []
            current_depth = frontier[0].depth + 1
            max_depth = max(max_depth, current_depth)
            pbar.set_postfix(frontier=len(frontier), depth=max_depth)

            # One Neo4j call for the entire frontier layer
            all_ids = [f.node_id for f in frontier]
            all_rows = graph.get_neighbours(all_ids)

            if not all_rows:
                break

            # One LLM call for the entire layer
            result = filter_relevant_neighbours(query, all_rows, visited)
            all_steps.extend(result.steps)

            # Track which frontier nodes produced at least one collected neighbour
            collected_from: set[str] = set()

            for node in result.to_collect:
                nid = node["to_id"]
                if nid not in visited and len(collected_nodes) < MAX_TOTAL_NODES:
                    visited.add(nid)
                    collected_nodes.append(node)
                    pbar.update(1)
                    if node.get("from_id"):
                        collected_from.add(node["from_id"])

            for node in result.to_expand:
                nid = node["to_id"]
                if nid in visited:
                    next_frontier.append(
                        _FrontierNode(nid, node["to_name"], current_depth, consecutive_misses=0)
                    )

            for pruned_id in result.pruned_ids:
                visited.add(pruned_id)

            # Per-branch consecutive-miss logic
            fnode_map = {f.node_id: f for f in frontier}
            for fnode in frontier:
                if fnode.node_id not in collected_from:
                    misses = fnode.consecutive_misses + 1
                    if misses < MAX_CONSECUTIVE_MISSES:
                        next_frontier.append(
                            _FrontierNode(fnode.node_id, fnode.node_name, current_depth, misses)
                        )

            frontier = next_frontier

    return collected_nodes, all_steps, max_depth
