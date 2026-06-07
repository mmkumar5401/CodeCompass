#!/usr/bin/env python3
"""
Write a new fact to the knowledge graph — for use by Claude Code.

Usage:
  python graph/remember_cli.py "Entity A" "RELATION_TYPE" "Entity B"

Example:
  python graph/remember_cli.py "Ripple Matrix" "GOVERNS" "Ripple Propagation"
"""
import sys
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, __file__.rsplit("/graph", 1)[0])

from config import neo4j_config
from graph.neo4j_client import Neo4jClient


def main():
    if len(sys.argv) < 4:
        print("Usage: python graph/remember_cli.py 'Entity A' 'RELATION_TYPE' 'Entity B'")
        sys.exit(1)

    from_entity = sys.argv[1].strip()
    rel_type    = sys.argv[2].strip().upper().replace(" ", "_")
    to_entity   = sys.argv[3].strip()

    if not from_entity or not rel_type or not to_entity:
        print("Error: all three arguments (from_entity, relation_type, to_entity) are required.")
        sys.exit(1)

    cfg   = neo4j_config()
    graph = Neo4jClient(uri=cfg["uri"], user=cfg["user"], password=cfg["password"])

    try:
        graph.remember_triple(from_entity, rel_type, to_entity, session_id="claude-code")
        print(f"[memory] wrote: ({from_entity}) --[{rel_type}]--> ({to_entity})")
    finally:
        graph.close()


if __name__ == "__main__":
    main()
