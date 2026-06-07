import anthropic
import json
import re
from dataclasses import dataclass, field
from dotenv import load_dotenv
from models.types import TraversalStep

load_dotenv(override=True)
_client = anthropic.Anthropic()

RELEVANCE_THRESHOLD = 0.7
MAX_NODES_PER_CALL = 50

FILTER_SYSTEM = """You are a graph navigator evaluating nodes for relevance to a query.

Score every node independently from 0.0 to 1.0.

Scoring guide:
- 0.8–1.0: clearly relevant — directly answers or supports the query
- 0.5–0.7: possibly relevant — related concept, worth exploring
- 0.0–0.4: not relevant — unrelated to the query

Return ONLY valid JSON with ALL nodes scored:
{
  "nodes": [
    {"node_id": "...", "relevance_score": 0.85, "reasoning": "..."}
  ]
}"""


@dataclass
class FilterResult:
    to_collect: list[dict]      # nodes to add to retrieved context
    to_expand: list[dict]       # nodes to add to next frontier
    pruned_ids: set[str]        # nodes that were pruned
    steps: list[TraversalStep]


def _format_prompt(query: str, rows: list[dict]) -> str:
    lines = [f"Query: {query}\n"]
    for row in rows:
        lines.append(
            f"ID: {row['to_id']} | Name: {row['to_name']!r} | "
            f"Type: {row['to_type']} | Via: [{row['rel_type']}] from {row['from_name']} (source_id: {row['from_id']})"
        )
    return "\n".join(lines)


def filter_relevant_neighbours(
    query: str,
    rows: list[dict],
    already_visited: set[str],
) -> FilterResult:
    """Score 1-hop neighbours in a single LLM call and partition into collect/expand/prune."""
    fresh_rows = [r for r in rows if r["to_id"] not in already_visited]
    if not fresh_rows:
        return FilterResult([], [], set(), [])

    batch = fresh_rows[:MAX_NODES_PER_CALL]
    prompt = _format_prompt(query, batch)

    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=FILTER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```$", "", raw.strip(), flags=re.MULTILINE)
        scored = json.loads(raw).get("nodes", [])
    except (json.JSONDecodeError, IndexError):
        # On parse failure, collect all nodes conservatively
        return FilterResult(
            to_collect=batch,
            to_expand=batch,
            pruned_ids=set(),
            steps=[],
        )

    score_map = {s["node_id"]: s for s in scored}

    to_collect: list[dict] = []
    to_expand: list[dict] = []
    pruned: set[str] = set()
    steps: list[TraversalStep] = []

    for row in batch:
        nid = row["to_id"]
        entry = score_map.get(nid, {})
        score = float(entry.get("relevance_score", 0.0))
        reasoning = entry.get("reasoning", "")

        steps.append(TraversalStep(
            node_id=nid,
            node_name=row["to_name"],
            relation_type=row["rel_type"],
            relevance_score=score,
            reasoning=reasoning,
        ))

        if score >= RELEVANCE_THRESHOLD:
            to_collect.append(row)
            to_expand.append(row)
        else:
            pruned.add(nid)

    return FilterResult(
        to_collect=to_collect,
        to_expand=to_expand,
        pruned_ids=pruned,
        steps=steps,
    )
