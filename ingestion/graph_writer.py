from tqdm import tqdm
from models.code_types import CodeTriple


def write_triples(client, triples: list[CodeTriple]) -> int:
    """Write triples to the local graph, deduplicating via (from, rel_type, to) key."""
    seen: set[tuple] = set()
    written = 0
    for triple in tqdm(triples, desc="Writing triples", unit="triple"):
        key = (triple.from_entity, triple.relation_type, triple.to_entity)
        if key in seen:
            continue
        seen.add(key)
        client.write_code_triple(triple, "", triple.source_file)
        written += 1
    return written
