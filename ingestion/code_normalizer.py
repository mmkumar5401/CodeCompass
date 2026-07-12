"""Haiku-powered normalization pass for raw code triples.

Tree-sitter extraction is syntactic — it knows `db.connect()` is a call
but not that `db` refers to a `DatabaseClient`. This module sends batches
of raw triples to Claude Haiku to:

  1. Resolve ambiguous/aliased entity names to their canonical form.
  2. Reclassify relation types where the syntactic guess was wrong.

Only entity names and relation types are sent — raw source code never
leaves the machine.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from rich.progress import track

from config import anthropic_api_key
from models.code_types import CodeTriple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE = 75  # triples per Haiku call — keeps prompts under ~2k tokens
MAX_RETRIES = 2

_SYSTEM_PROMPT = """\
You are a code knowledge graph normalizer.

You receive a JSON array of code triples extracted by a syntax parser.
Each triple has: from_entity, from_type, relation_type, to_entity, to_type.

Your job:
1. Resolve aliased or abbreviated entity names to their full canonical form
   when the alias is obvious from context (e.g. "db" → "DatabaseClient" if
   another triple clarifies this). Do NOT guess — leave the name unchanged
   if you are not certain.
2. Correct the relation_type if the parser clearly mis-classified it.
   Allowed types: CALLS, IMPORTS, INHERITS, DEFINED_IN, STYLES, HAS_CLASS,
   POSTS_TO, INCLUDES, USED_BY, OVERRIDES, RAISES, RETURNS_TYPE.
3. Correct entity types if obviously wrong.
   Allowed types: function, class, module, css_selector, html_element,
   scss_mixin, scss_variable, endpoint, css_class, file, interface, trait,
   enum, property, constant.

Return the same JSON array with corrections applied.
Do NOT add, remove, or reorder triples.
Do NOT include any text outside the JSON array.
"""


def normalize_triples(triples: list[CodeTriple], progress: bool = False) -> list[CodeTriple]:
    """Run the Haiku normalization pass over all triples.

    Splits into batches of BATCH_SIZE, calls Haiku once per batch, and
    returns the full corrected list. Falls back to the original triples if
    a batch fails after MAX_RETRIES.
    """
    if not triples:
        return []

    client = anthropic.Anthropic(api_key=anthropic_api_key())
    batches = _split_into_batches(triples, BATCH_SIZE)
    normalized: list[CodeTriple] = []

    batches_iter = track(batches, description="Normalizing batches") if progress else batches

    for batch in batches_iter:
        corrected = _normalize_batch(client, batch)
        normalized.extend(corrected)

    return normalized


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_batch(client: anthropic.Anthropic, batch: list[CodeTriple]) -> list[CodeTriple]:
    """Send one batch to Haiku and return corrected triples.

    Falls back to the original batch if the API response cannot be parsed.
    """
    raw = _triples_to_dicts(batch)
    payload = json.dumps(raw, ensure_ascii=False)

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": payload}],
            )
            corrected_dicts = json.loads(response.content[0].text)
            return _dicts_to_triples(corrected_dicts, batch)
        except (json.JSONDecodeError, KeyError, IndexError):
            if attempt == MAX_RETRIES:
                # Return originals rather than crashing the pipeline
                return batch
            continue

    return batch


def _split_into_batches(triples: list[CodeTriple], size: int) -> list[list[CodeTriple]]:
    return [triples[i:i + size] for i in range(0, len(triples), size)]


def _triples_to_dicts(triples: list[CodeTriple]) -> list[dict[str, Any]]:
    return [
        {
            "from_entity": t.from_entity,
            "from_type": t.from_type,
            "relation_type": t.relation_type,
            "to_entity": t.to_entity,
            "to_type": t.to_type,
        }
        for t in triples
    ]


def _dicts_to_triples(corrected: list[dict], originals: list[CodeTriple]) -> list[CodeTriple]:
    """Merge corrected dict fields back into the original CodeTriple objects.

    Preserves source_file and line_number (which Haiku doesn't see) from
    the originals. Falls back to the original triple if a corrected entry
    is malformed.
    """
    result: list[CodeTriple] = []
    for i, original in enumerate(originals):
        if i >= len(corrected):
            result.append(original)
            continue
        patch = corrected[i]
        try:
            result.append(CodeTriple(
                from_entity=patch.get("from_entity", original.from_entity),
                from_type=patch.get("from_type", original.from_type),
                relation_type=patch.get("relation_type", original.relation_type),
                to_entity=patch.get("to_entity", original.to_entity),
                to_type=patch.get("to_type", original.to_type),
                source_file=original.source_file,
                line_number=original.line_number,
            ))
        except (TypeError, AttributeError):
            result.append(original)
    return result
