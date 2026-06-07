"""Bridge detector — finds and validates cross-project entity matches.

After ingestion, this module compares entity names across two or more
project graphs, proposes matches to Haiku for validation, and writes
confirmed BRIDGE edges to the master graph.

Only entity names are sent to Haiku — no source code.
"""

from __future__ import annotations

import json

import anthropic

from config import anthropic_api_key
from graph.code_graph_client import CodeGraphClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_BRIDGE_CONFIDENCE = 0.7
CANDIDATE_BATCH_SIZE = 50

_SYSTEM_PROMPT = """\
You are a cross-project code dependency analyst.

You receive two lists of entity names from different projects.
Identify pairs of entities that refer to the same real-world concept and
are likely connected across these projects (e.g. a shared schema, a shared
utility, an API contract that one project exposes and the other consumes).

For each match, return:
{
  "from_entity": "<name from project A>",
  "to_entity":   "<name from project B>",
  "bridge_type": "<SHARES_SCHEMA | CALLS_API | IMPLEMENTS | EXTENDS | MIRRORS>",
  "confidence":  0.0–1.0,
  "reasoning":   "<one sentence>"
}

Return a JSON array of matches. Return [] if there are no confident matches.
Only include matches with confidence >= 0.7.
Do NOT include any text outside the JSON array.
"""


def detect_bridges(
    project_a: str,
    project_b: str,
    client_a: CodeGraphClient,
    client_b: CodeGraphClient,
    master_client: CodeGraphClient,
) -> int:
    """Detect and write BRIDGE edges between project_a and project_b.

    Returns the number of bridge edges written.
    """
    entities_a = client_a.get_all_entity_names(project_a)
    entities_b = client_b.get_all_entity_names(project_b)

    if not entities_a or not entities_b:
        return 0

    names_a = [e["name"] for e in entities_a]
    names_b = [e["name"] for e in entities_b]

    # Find name overlaps — obvious bridges that don't need Haiku
    overlap_names = set(names_a) & set(names_b)
    candidates_a = [e for e in entities_a if e["name"] in overlap_names]
    candidates_b = [e for e in entities_b if e["name"] in overlap_names]

    # Build an id lookup for writing edges
    id_map_a = {e["name"]: e["id"] for e in entities_a}
    id_map_b = {e["name"]: e["id"] for e in entities_b}

    # Validate candidates with Haiku (batched)
    validated = _validate_with_haiku(candidates_a, candidates_b, names_a, names_b)

    bridges_written = 0
    for match in validated:
        from_id = id_map_a.get(match["from_entity"])
        to_id = id_map_b.get(match["to_entity"])
        if from_id and to_id:
            master_client.write_bridge_edge(
                from_entity_id=from_id,
                to_entity_id=to_id,
                bridge_type=match["bridge_type"],
                confidence=match["confidence"],
                via=f"{project_a}↔{project_b}",
            )
            bridges_written += 1

    return bridges_written


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_with_haiku(
    candidates_a: list[dict],
    candidates_b: list[dict],
    all_names_a: list[str],
    all_names_b: list[str],
) -> list[dict]:
    """Ask Haiku to validate and classify the bridge candidates."""
    if not candidates_a or not candidates_b:
        return []

    haiku = anthropic.Anthropic(api_key=anthropic_api_key())

    payload = json.dumps({
        "project_a_candidates": [e["name"] for e in candidates_a[:CANDIDATE_BATCH_SIZE]],
        "project_b_candidates": [e["name"] for e in candidates_b[:CANDIDATE_BATCH_SIZE]],
        "project_a_all_entities": all_names_a[:200],  # context for Haiku
        "project_b_all_entities": all_names_b[:200],
    })

    try:
        response = haiku.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
        matches = json.loads(response.content[0].text)
        return [m for m in matches if m.get("confidence", 0) >= MIN_BRIDGE_CONFIDENCE]
    except (json.JSONDecodeError, KeyError, IndexError, Exception):
        return []
