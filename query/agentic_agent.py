import anthropic
import json
import time
import uuid
from dotenv import load_dotenv
from graph.neo4j_client import Neo4jClient
from query.seed_finder import find_seed_nodes
from models.types import TraversalStep, QueryResult

load_dotenv(override=True)
_client = anthropic.Anthropic()

TRAVERSAL_MODEL = "claude-haiku-4-5-20251001"  # fast traversal
ANSWER_MODEL = "claude-sonnet-4-6"             # deep synthesis
THINKING_BUDGET = 1500                          # tokens for synthesis reasoning

TRAVERSAL_SYSTEM = """You are a knowledge graph explorer with full read, write, and ingest access to long-term memory.

You are given seed nodes. Use the three tools as needed:

get_neighbours — explore the existing graph
- Pass 8–12 node names per call
- Start with all seed nodes in your first call
- Follow relevant neighbours in subsequent calls
- For broad questions 4–6 calls is usually enough; for specific questions 2–3 is sufficient

remember — commit a fact EXPLICITLY present in edges you just received
- Only use for facts directly stated in get_neighbours results, not inferences
- Do NOT connect entities from different domains unless an edge explicitly links them
- Do NOT use ALL_CAPS_UNDERSCORES relation types for speculative connections
- Do not duplicate facts already in the graph

ingest_source — pull in new knowledge not yet in the graph
- Use when the query requires information that isn't reachable through get_neighbours
- Pass a URL to fetch web content, or raw text to ingest directly
- After ingestion, use get_neighbours on the returned node names to continue exploration

When done, output ONLY the word: DONE"""

ANSWER_SYSTEM = """You are an expert at synthesizing knowledge graph data into clear, insightful explanations.

You are given a set of graph edges (entity → relationship → entity) collected by traversal.
Your job is to answer the query in fluent, well-structured prose — like a knowledgeable person explaining the topic.

Rules:
- Write naturally. Do not list raw graph edges or relationship types as bullet points.
- Use the graph edges as the factual backbone of your explanation, not as the output format.
- Organise your answer logically (e.g. what it is → how it works → why it matters).
- You may mention relationship names inline when it adds precision (e.g. "X depends on Y"), but sparingly.
- Every claim you make must be traceable to a specific edge in the provided list.
- Do not draw connections between separate domains unless an edge explicitly links them.
- If the edges are insufficient to answer part of the query, say so rather than speculating.
- Aim for depth and clarity, not exhaustive enumeration."""

_TOOLS = [
    {
        "name": "get_neighbours",
        "description": (
            "Fetch direct neighbours for one or more nodes in a single call. "
            "Pass a list of exact node names (from the seed list or previous results). "
            "Batching more names per call is more efficient — pass 8–12 at a time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact names of nodes to explore (pass 8–12 at a time).",
                }
            },
            "required": ["node_names"],
        },
    },
    {
        "name": "ingest_source",
        "description": (
            "Ingest a new document or URL into long-term memory. "
            "Use when the query requires knowledge that isn't reachable through get_neighbours. "
            "Chunks the content, extracts entities and relationships, and writes them to the graph immediately. "
            "Returns newly added node names — use get_neighbours on them to continue exploration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "A URL to fetch, or raw text to ingest directly.",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["url", "text"],
                    "description": "'url' to fetch and ingest web content; 'text' to ingest the string directly.",
                },
            },
            "required": ["source", "source_type"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Commit a new fact to long-term memory. Use this when you discover or infer "
            "a relationship during traversal that should persist across sessions. "
            "The fact is written to the graph immediately and tagged with this session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "from_entity": {
                    "type": "string",
                    "description": "Name of the source entity.",
                },
                "relation_type": {
                    "type": "string",
                    "description": "Relationship type in ALL_CAPS_UNDERSCORES, e.g. CAUSES, EXTENDS, DEPENDS_ON.",
                },
                "to_entity": {
                    "type": "string",
                    "description": "Name of the target entity.",
                },
            },
            "required": ["from_entity", "relation_type", "to_entity"],
        },
    },
]


def _seed_text(seeds: list[dict]) -> str:
    return "\n".join(
        f"  Name: {n['name']!r} | Type: {n['type']}"
        for n in seeds
    )


def _process_get_neighbours(
    block,
    name_to_id: dict[str, str],
    id_to_name: dict[str, str],
    explored_names: set[str],
    graph: Neo4jClient,
    tool_call_count: int,
    all_edges: list[dict],
    traversal_steps: list[TraversalStep],
) -> tuple[dict, int]:
    """Execute one batched get_neighbours call. Returns (tool_result, nodes_newly_explored)."""
    requested = block.input.get("node_names", [])
    if isinstance(requested, str):
        requested = [requested]

    valid: list[tuple[str, str]] = []
    skipped: list[str] = []

    for name in requested:
        name = name.strip()
        if name in explored_names:
            skipped.append(f"'{name}' already explored")
            continue
        nid = name_to_id.get(name)
        if not nid:
            skipped.append(f"'{name}' not found")
            continue
        valid.append((name, nid))

    if not valid:
        feedback = "No new nodes to explore. " + "; ".join(skipped) if skipped else "No valid nodes provided."
        return {"type": "tool_result", "tool_use_id": block.id, "content": feedback}, 0

    for name, _ in valid:
        explored_names.add(name)

    newly_explored = len(valid)
    node_ids = [nid for _, nid in valid]
    exclude_ids = [name_to_id[n] for n in explored_names if n in name_to_id]
    rows = graph.get_neighbours(node_ids, exclude_ids=exclude_ids)

    for r in rows:
        name_to_id.setdefault(r["from_name"], r["from_id"])
        name_to_id.setdefault(r["to_name"], r["to_id"])
        id_to_name.setdefault(r["from_id"], r["from_name"])
        id_to_name.setdefault(r["to_id"], r["to_name"])

    names_str = ", ".join(n for n, _ in valid)
    print(f"  [{tool_call_count + newly_explored}] exploring: {names_str}", flush=True)

    for name, nid in valid:
        traversal_steps.append(TraversalStep(
            node_id=nid,
            node_name=name,
            relation_type="→ explored",
            relevance_score=1.0,
            reasoning="Selected by Haiku during traversal",
        ))

    display_rows = [
        {"from": r["from_name"], "relation": r["rel_type"], "to": r["to_name"]}
        for r in rows
    ]
    all_edges.extend(display_rows)

    content = json.dumps(display_rows) if display_rows else "No new neighbours found."
    if skipped:
        content += f"\n\nNote: {'; '.join(skipped)}."

    return {"type": "tool_result", "tool_use_id": block.id, "content": content}, newly_explored


def _validate_remember(
    from_entity: str,
    rel_type: str,
    to_entity: str,
    all_edges: list[dict],
) -> bool:
    """
    Quick Haiku check: is this fact directly supported by recently seen edges?
    Prevents speculative cross-domain connections from entering permanent memory.
    """
    edges_str = "\n".join(
        f"({e['from']}) --[{e['relation']}]--> ({e['to']})"
        for e in all_edges[-40:]
    ) or "(no edges seen yet)"

    prompt = (
        f"Proposed fact to write to permanent memory:\n"
        f"  ({from_entity}) --[{rel_type}]--> ({to_entity})\n\n"
        f"Recently seen graph edges:\n{edges_str}\n\n"
        "Is this fact DIRECTLY and EXPLICITLY supported by the edges above "
        "(i.e. it is stated outright, not merely plausible or inferred across domains)?\n"
        "Answer only YES or NO."
    )
    response = _client.messages.create(
        model=TRAVERSAL_MODEL,
        max_tokens=5,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip().upper().startswith("Y")


def _process_remember(
    block,
    graph: Neo4jClient,
    session_id: str,
    name_to_id: dict[str, str],
    remembered: list[dict],
    all_edges: list[dict],
) -> dict:
    """Execute one remember call — validates then writes a new fact to the graph."""
    from_entity = block.input.get("from_entity", "").strip()
    rel_type = block.input.get("relation_type", "").strip()
    to_entity = block.input.get("to_entity", "").strip()

    if not from_entity or not rel_type or not to_entity:
        return {"type": "tool_result", "tool_use_id": block.id, "content": "Error: missing fields."}

    # Guard: validate the fact is grounded before writing to permanent memory
    if not _validate_remember(from_entity, rel_type, to_entity, all_edges):
        print(f"  [memory] rejected: ({from_entity}) --[{rel_type.upper()}]--> ({to_entity}) — not grounded", flush=True)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": f"Rejected: this fact is not directly supported by the edges seen. Do not use remember for cross-domain inferences.",
        }

    graph.remember_triple(from_entity, rel_type, to_entity, session_id)

    import uuid as _uuid
    name_to_id.setdefault(from_entity, str(_uuid.uuid5(_uuid.NAMESPACE_DNS, from_entity.lower())))
    name_to_id.setdefault(to_entity, str(_uuid.uuid5(_uuid.NAMESPACE_DNS, to_entity.lower())))

    fact = {"from": from_entity, "relation": rel_type.upper(), "to": to_entity}
    remembered.append(fact)
    print(f"  [memory] wrote: ({from_entity}) --[{rel_type.upper()}]--> ({to_entity})", flush=True)

    return {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": f"Remembered: ({from_entity}) --[{rel_type.upper()}]--> ({to_entity})",
    }


def _fetch_url(url: str) -> str:
    """
    Fetch a URL and return clean text.
    - arxiv abs → redirects to PDF, extracts with PyPDF2
    - Everything else → strips HTML tags
    """
    import re
    import io
    import urllib.request

    HEADERS = {"User-Agent": "Mozilla/5.0"}

    # arxiv: prefer PDF over noisy HTML abstract page
    arxiv_match = re.match(r"https?://arxiv\.org/abs/(.+?)(?:\s|$)", url)
    if arxiv_match:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_match.group(1)}"
        print(f"  [ingest] arxiv detected — fetching PDF: {pdf_url}", flush=True)
        try:
            import PyPDF2
            req = urllib.request.Request(pdf_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                pdf_bytes = resp.read()
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(pages).strip()
            if text:
                return text
            # Fall through to HTML if PDF extraction yields nothing
        except Exception as e:
            print(f"  [ingest] PDF fetch failed ({e}), falling back to HTML", flush=True)

    # Generic HTML fetch
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _process_ingest_source(
    block,
    graph: Neo4jClient,
    session_id: str,
    name_to_id: dict[str, str],
    id_to_name: dict[str, str],
) -> dict:
    """Fetch + chunk + extract + write a new source mid-session."""
    from ingestion.chunker import chunk_text
    from ingestion.reader_agent import extract_triples_parallel_sync

    source = block.input.get("source", "").strip()
    source_type = block.input.get("source_type", "text")

    if not source:
        return {"type": "tool_result", "tool_use_id": block.id, "content": "Error: no source provided."}

    # --- Fetch content ---
    if source_type == "url":
        print(f"  [ingest] fetching {source[:80]}...", flush=True)
        try:
            text = _fetch_url(source)
        except Exception as e:
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"Failed to fetch URL: {e}"}
    else:
        text = source

    if not text:
        return {"type": "tool_result", "tool_use_id": block.id, "content": "No content to ingest."}

    # --- Chunk + extract (parallel) ---
    chunks = chunk_text(text)
    print(f"  [ingest] {len(chunks)} chunks — extracting triples in parallel...", flush=True)
    all_triples = extract_triples_parallel_sync(chunks)

    print(f"  [ingest] extracted {len(all_triples)} triples — writing to graph...", flush=True)

    # --- Write to graph tagged with this session ---
    new_names: set[str] = set()
    for triple in all_triples:
        graph.write_triple(triple, session_id=session_id)
        for entity in (triple.entity_from, triple.entity_to):
            name_to_id.setdefault(entity.name, entity.id)
            id_to_name.setdefault(entity.id, entity.name)
            new_names.add(entity.name)

    print(f"  [ingest] done — {len(new_names)} new entities available", flush=True)

    sample = sorted(new_names)[:20]
    return {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": (
            f"Ingested {len(all_triples)} triples ({len(new_names)} entities) from source.\n"
            f"Sample of new nodes: {sample}\n"
            "Use get_neighbours on any of these to explore the new knowledge."
        ),
    }


def run_agentic_agent(
    question: str,
    graph: Neo4jClient,
    session_id: str | None = None,
) -> QueryResult:
    """
    Hybrid traversal: Haiku drives fast batched graph exploration (with write-back),
    then Sonnet reasons deeply (extended thinking) over the collected subgraph.

    session_id tags every fact written this session so memory can be scoped,
    aged, or forgotten independently of ingested facts.
    """
    if not session_id:
        session_id = str(uuid.uuid4())[:8]

    seeds = find_seed_nodes(question, graph)
    if not seeds:
        return QueryResult(
            answer="No relevant starting nodes found in the knowledge graph.",
            reasoning_path=[],
            nodes_explored=0,
            nodes_retrieved=0,
            hops_taken=0,
        )

    print(f"\n  [session {session_id}]", flush=True)

    _start = time.perf_counter()
    name_to_id: dict[str, str] = {s["name"]: s["id"] for s in seeds}
    id_to_name: dict[str, str] = {s["id"]: s["name"] for s in seeds}

    initial_content = (
        f"Seed nodes found for your query:\n{_seed_text(seeds)}\n\n"
        f"Query: {question}\n\n"
        "Explore the graph using get_neighbours. Pass multiple node names per call. "
        "Use remember to commit any new facts you discover."
    )

    messages = [{"role": "user", "content": initial_content}]
    traversal_steps: list[TraversalStep] = []
    explored_names: set[str] = set()
    ingested_sources: set[str] = set()   # dedup by url/content hash
    all_edges: list[dict] = []
    remembered: list[dict] = []
    ingested_count = 0
    tool_call_count = 0
    max_depth_reached = 0

    # --- Haiku traversal loop ---
    while True:
        response = _client.messages.create(
            model=TRAVERSAL_MODEL,
            max_tokens=1024,
            system=TRAVERSAL_SYSTEM,
            tools=_TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            candidates = [n for n in name_to_id if n not in explored_names]
            if not candidates or tool_call_count == 0:
                break

            candidate_list = "\n".join(f"  - {n}" for n in candidates[:10])
            print(f"  [confirming — {len(candidates)} unexplored nodes available]", flush=True)
            messages.append({
                "role": "user",
                "content": (
                    f"You indicated you're done. These nodes appeared during traversal "
                    f"but haven't been explored yet:\n{candidate_list}\n\n"
                    "Are you confident you have enough to answer the query, or would "
                    "you like to explore any of these? If done, output DONE. "
                    "Otherwise use get_neighbours (you can pass multiple names at once)."
                ),
            })
            confirmation = _client.messages.create(
                model=TRAVERSAL_MODEL,
                max_tokens=1024,
                system=TRAVERSAL_SYSTEM,
                tools=_TOOLS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": confirmation.content})
            if confirmation.stop_reason == "end_turn":
                break
            response = confirmation

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            if block.name == "ingest_source":
                source_key = block.input.get("source", "").strip()[:200]
                if source_key in ingested_sources:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Already ingested this source in the current session. Use get_neighbours to explore the nodes from the earlier ingest.",
                    })
                else:
                    ingested_sources.add(source_key)
                    result = _process_ingest_source(block, graph, session_id, name_to_id, id_to_name)
                    ingested_count += 1
                    tool_results.append(result)

            elif block.name == "remember":
                result = _process_remember(block, graph, session_id, name_to_id, remembered, all_edges)
                tool_results.append(result)

            elif block.name == "get_neighbours":
                result, newly = _process_get_neighbours(
                    block, name_to_id, id_to_name, explored_names,
                    graph, tool_call_count, all_edges, traversal_steps,
                )
                tool_call_count += newly
                max_depth_reached = tool_call_count
                tool_results.append(result)

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    traversal_time = time.perf_counter() - _start
    parts = [f"gathered {len(all_edges)} edges across {tool_call_count} nodes"]
    if ingested_count:
        parts.append(f"ingested {ingested_count} new source(s)")
    if remembered:
        parts.append(f"wrote {len(remembered)} new fact(s) to memory")
    parts.append(f"{traversal_time:.1f}s")
    print(f"\n  {' · '.join(parts)} — generating answer...\n", flush=True)

    # --- Sonnet synthesis with extended thinking + streaming ---
    graph_context = "\n".join(
        f"({e['from']}) --[{e['relation']}]--> ({e['to']})" for e in all_edges
    )

    thinking_text = ""
    answer = ""
    current_block_type = None

    with _client.beta.messages.stream(
        model=ANSWER_MODEL,
        max_tokens=THINKING_BUDGET + 2000,
        thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
        system=ANSWER_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Query: {question}\n\nGraph edges collected:\n{graph_context}",
        }],
        betas=["interleaved-thinking-2025-05-14"],
    ) as stream:
        for event in stream:
            if event.type == "content_block_start":
                current_block_type = event.content_block.type
                if current_block_type == "thinking":
                    print("── Thinking ──────────────────────────────────────────────────────────────────")
                elif current_block_type == "text":
                    print("── Answer ────────────────────────────────────────────────────────────────────")

            elif event.type == "content_block_delta":
                delta = event.delta
                if delta.type == "thinking_delta":
                    print(delta.thinking, end="", flush=True)
                    thinking_text += delta.thinking
                elif delta.type == "text_delta":
                    print(delta.text, end="", flush=True)
                    answer += delta.text

            elif event.type == "content_block_stop":
                if current_block_type in ("thinking", "text"):
                    print("\n──────────────────────────────────────────────────────────────────────────────\n")

    return QueryResult(
        answer=answer,
        reasoning_path=traversal_steps,
        nodes_explored=len(explored_names),
        nodes_retrieved=len(explored_names),
        hops_taken=max_depth_reached,
    )
