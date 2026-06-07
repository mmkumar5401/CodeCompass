from tqdm import tqdm
from graph.neo4j_client import Neo4jClient
from models.types import Triple


def write_triples(client: Neo4jClient, triples: list[Triple]) -> int:
    """Write triples to Neo4j, deduplicating via (from, rel_type, to) key"""
    seen: set[tuple] = set()
    written = 0
    for triple in tqdm(triples, desc="Writing to Neo4j", unit="triple"):
        key = (triple.entity_from.id, triple.relation.type, triple.entity_to.id)
        if key in seen:
            continue
        seen.add(key)
        client.write_triple(triple)
        written += 1
    return written
