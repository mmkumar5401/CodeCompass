#!/usr/bin/env python3
"""
Write multiple facts to the knowledge graph in one call — for use by Claude Code.

Claude Code extracts triples natively (no API cost), then passes them here
as a JSON array to write all at once.

Usage:
  python graph/remember_batch_cli.py '[
    {"from": "Entity A", "relation": "CAUSES", "to": "Entity B"},
    {"from": "Entity B", "relation": "DEPENDS_ON", "to": "Entity C"}
  ]'

  # Or pipe JSON from a file:
  python graph/remember_batch_cli.py "$(cat triples.json)"

Relation types should be ALL_CAPS_UNDERSCORES (CAUSES, DEPENDS_ON, HAS_COMPONENT, etc.)
"""
import sys
import json
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, __file__.rsplit("/graph", 1)[0])

from config import neo4j_config
from graph.neo4j_client import Neo4jClient


def main():
    if len(sys.argv) < 2:
        print("Usage: python graph/remember_batch_cli.py '[{\"from\": \"A\", \"relation\": \"R\", \"to\": \"B\"}, ...]'")
        sys.exit(1)

    raw = sys.argv[1].strip()
    try:
        triples = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON — {e}")
        sys.exit(1)

    if not isinstance(triples, list):
        print("Error: expected a JSON array of triples.")
        sys.exit(1)

    cfg   = neo4j_config()
    graph = Neo4jClient(uri=cfg["uri"], user=cfg["user"], password=cfg["password"])

    written = 0
    skipped = 0

    try:
        for t in triples:
            from_entity = str(t.get("from", "")).strip()
            rel_type    = str(t.get("relation", "")).strip().upper().replace(" ", "_")
            to_entity   = str(t.get("to", "")).strip()

            if not from_entity or not rel_type or not to_entity:
                print(f"  [skip] incomplete triple: {t}")
                skipped += 1
                continue

            graph.remember_triple(from_entity, rel_type, to_entity, session_id="claude-code")
            print(f"  [memory] wrote: ({from_entity}) --[{rel_type}]--> ({to_entity})")
            written += 1
    finally:
        graph.close()

    print(f"\n[done] {written} facts written, {skipped} skipped.")


if __name__ == "__main__":
    main()
