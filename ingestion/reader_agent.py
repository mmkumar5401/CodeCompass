import anthropic
import json
import asyncio
import uuid
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from tqdm.asyncio import tqdm
from tqdm import tqdm as tqdm_sync
from models.types import Entity, Relation, Triple

load_dotenv(override=True)
# Sync client — each call is run in a thread pool to avoid blocking the event loop
_client = anthropic.Anthropic()

# Cached system prompt block — same every call, so cache it after the first hit
_EXTRACTION_SYSTEM = [
    {
        "type": "text",
        "text": """You are a knowledge graph extraction agent.
Given a text chunk, extract all meaningful entities and the relationships between them.

Rules:
- Entities: concrete nouns, concepts, people, places, events, systems, components
- Relations: verbs or relationship types connecting entities (CAUSES, DEPENDS_ON, HAS_COMPONENT, USED_BY, etc.)
- Weight: confidence in the relation from 0.0 to 1.0
- Be selective — only extract clear, meaningful relationships
- Use consistent entity names (no duplicates with different casing)

Return ONLY valid JSON, no other text:
{
  "entities": [
    {"name": "Entity Name", "type": "Concept|Person|Place|Event|System", "description": "brief description"}
  ],
  "relations": [
    {"from": "Entity A", "to": "Entity B", "type": "RELATION_TYPE", "weight": 0.9, "description": "brief explanation"}
  ]
}""",
        "cache_control": {"type": "ephemeral"},
    }
]

# Expose plain text for any code that imports EXTRACTION_SYSTEM by name
EXTRACTION_SYSTEM = _EXTRACTION_SYSTEM[0]["text"]

# How many Haiku calls to run concurrently.
# Haiku rate limits are generous — 15 keeps throughput high without hitting 429s.
MAX_CONCURRENT = 15


def _extract_triples_sync(chunk: str) -> list[Triple]:
    """Blocking extraction — called from a thread pool."""
    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=_EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": f"Extract knowledge graph from:\n\n{chunk}"}],
    )

    try:
        raw = response.content[0].text
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip(), flags=re.MULTILINE)
        raw = re.sub(r"```$", "", raw.strip(), flags=re.MULTILINE)
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, IndexError) as e:
        print(f"[reader_agent] JSON parse failed: {e} | raw: {raw[:200]!r}")
        return []

    entity_map: dict[str, Entity] = {}
    for e in data.get("entities", []):
        # Normalise: strip whitespace, collapse internal spaces, strip trailing punctuation
        name = re.sub(r"\s+", " ", e.get("name", "").strip()).strip(".,;:()")
        if not name:
            continue
        eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, name.lower()))
        entity_map[name] = Entity(
            id=eid,
            name=name,
            type=e.get("type", "Concept"),
            description=e.get("description"),
            source_chunk=chunk[:100],
        )

    triples: list[Triple] = []
    for r in data.get("relations", []):
        from_entity = entity_map.get(r.get("from", ""))
        to_entity = entity_map.get(r.get("to", ""))
        if not from_entity or not to_entity:
            continue
        relation = Relation(
            from_id=from_entity.id,
            to_id=to_entity.id,
            type=r.get("type", "RELATED_TO"),
            weight=float(r.get("weight", 0.8)),
            description=r.get("description"),
        )
        triples.append(Triple(from_entity, relation, to_entity))

    return triples


def extract_triples_parallel_sync(chunks: list[str], max_workers: int = MAX_CONCURRENT) -> list[Triple]:
    """
    Run extraction on all chunks in parallel using a thread pool.
    Used for mid-session ingest_source where we're already in a sync context.
    """
    all_triples: list[Triple] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_extract_triples_sync, chunk): i for i, chunk in enumerate(chunks)}
        for future in tqdm_sync(as_completed(futures), total=len(futures), desc="Extracting", unit="chunk"):
            try:
                all_triples.extend(future.result())
            except Exception as e:
                print(f"[reader_agent] chunk failed: {e}")
    return all_triples


async def extract_triples(chunk: str) -> list[Triple]:
    """Async wrapper — offloads blocking API call to a thread."""
    return await asyncio.to_thread(_extract_triples_sync, chunk)


async def ingest_chunks_parallel(
    chunks: list[str], max_concurrent: int = MAX_CONCURRENT
) -> list[Triple]:
    """Run extraction on all chunks with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_extract(chunk: str) -> list[Triple]:
        async with semaphore:
            return await extract_triples(chunk)

    tasks = [bounded_extract(c) for c in chunks]
    results = await tqdm.gather(*tasks, desc="Extracting triples", unit="chunk")
    return [triple for batch in results for triple in batch]
