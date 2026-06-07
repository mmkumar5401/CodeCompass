#!/usr/bin/env python3
"""
Graph retrieval tool for Claude Code integration.

Fetches a relevant subgraph for a question using keyword-based seed finding
and BFS traversal — no LLM calls, no API credits. Outputs plain text edges
that Claude Code can reason about directly.

Usage:
  python graph/query_cli.py "What is ripple propagation?"
  python graph/query_cli.py "What is ripple propagation?" --hops 3
  python graph/query_cli.py --seeds "Ripple Propagation,Knowledge Tracing"
  python graph/query_cli.py --list-nodes
"""
import sys
import argparse
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, __file__.rsplit("/graph", 1)[0])  # ensure project root is on path

from config import neo4j_config
from graph.neo4j_client import Neo4jClient


def list_nodes(graph: Neo4jClient) -> str:
    nodes = graph.get_all_node_names()
    lines = [f"  {n['name']} ({n['type']})" for n in nodes]
    return f"{len(nodes)} nodes in graph:\n" + "\n".join(lines)


def get_subgraph(
    graph: Neo4jClient,
    question: str = "",
    seed_names: list[str] | None = None,
    max_hops: int = 2,
    max_nodes: int = 60,
) -> str:
    # --- Seed finding (keyword match, no LLM) ---
    if seed_names:
        seeds = graph.find_nodes_by_name(seed_names)
    else:
        # Extract meaningful words from the question
        stopwords = {"what", "how", "why", "when", "where", "who", "is", "are", "the",
                     "a", "an", "in", "of", "to", "and", "or", "for", "with", "does",
                     "do", "can", "you", "me", "tell", "explain", "describe", "give"}
        words = [w.strip("?.,!") for w in question.lower().split()
                 if len(w) > 3 and w not in stopwords]
        seeds = graph.find_nodes_by_name(words[:8])

    if not seeds:
        return "No relevant nodes found. Try --list-nodes to see what's in the graph."

    # --- BFS traversal ---
    visited_ids: set[str] = {s["id"] for s in seeds}
    frontier_ids: list[str] = [s["id"] for s in seeds]
    all_edges: list[str] = []
    nodes_visited = len(seeds)

    for hop in range(max_hops):
        if nodes_visited >= max_nodes:
            break
        rows = graph.get_neighbours(frontier_ids, exclude_ids=list(visited_ids))
        if not rows:
            break

        new_ids: list[str] = []
        for r in rows:
            all_edges.append(f"({r['from_name']}) --[{r['rel_type']}]--> ({r['to_name']})")
            if r["to_id"] not in visited_ids:
                visited_ids.add(r["to_id"])
                new_ids.append(r["to_id"])
                nodes_visited += 1

        frontier_ids = new_ids

    seed_names_str = ", ".join(s["name"] for s in seeds)
    edges_str = "\n".join(all_edges) if all_edges else "(no edges found)"

    return (
        f"Query: {question}\n"
        f"Seed nodes: {seed_names_str}\n"
        f"Nodes explored: {nodes_visited}  |  Edges collected: {len(all_edges)}\n"
        f"\nGraph edges:\n{edges_str}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve a subgraph for Claude Code to reason about."
    )
    parser.add_argument("question", nargs="?", default="", help="Natural language question")
    parser.add_argument("--seeds", help="Comma-separated seed node names (bypasses keyword search)")
    parser.add_argument("--hops", type=int, default=2, help="BFS depth (default 2)")
    parser.add_argument("--max-nodes", type=int, default=60, help="Max nodes to explore (default 60)")
    parser.add_argument("--list-nodes", action="store_true", help="List all nodes in the graph")
    args = parser.parse_args()

    cfg = neo4j_config()
    graph = Neo4jClient(uri=cfg["uri"], user=cfg["user"], password=cfg["password"])

    try:
        if args.list_nodes:
            print(list_nodes(graph))
        else:
            if not args.question and not args.seeds:
                parser.print_help()
                sys.exit(1)
            seed_list = [s.strip() for s in args.seeds.split(",")] if args.seeds else None
            print(get_subgraph(graph, args.question, seed_list, args.hops, args.max_nodes))
    finally:
        graph.close()


if __name__ == "__main__":
    main()
