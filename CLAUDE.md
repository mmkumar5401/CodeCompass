# GraphRAG — Claude Code Instructions

This project is a persistent memory system for LLMs backed by a Neo4j knowledge graph.
You have full read, write, and ingest access to the graph from here.

---

## Reading the graph

When asked any question about the knowledge graph, run the retrieval tool first:

```bash
cd /Users/manojkumarmuthukumaran/Documents/Work/graphrag
python graph/query_cli.py "your question here"
```

This returns seed nodes and a subgraph of edges. Reason over those edges to answer the question.
Do not hallucinate facts — if the graph doesn't contain enough information, say so.

**Options:**
```bash
# More hops for broader questions
python graph/query_cli.py "question" --hops 3

# Specific seed nodes (skip keyword search)
python graph/query_cli.py --seeds "Ripple Propagation,Knowledge Tracing"

# See all nodes in the graph
python graph/query_cli.py --list-nodes
```

---

## Ingesting new sources — two modes

### Mode 1: Native extraction (zero API credits, YOU do the extraction)

Use this when Anthropic API credits are unavailable or you want zero cost.
You read the content and extract the triples yourself, then write them in one batch call.

**For a local file:**
1. Read the file directly using your Read tool
2. Extract all meaningful entities and relationships from the content
3. Write them all at once:
```bash
python graph/remember_batch_cli.py '[
  {"from": "Entity A", "relation": "RELATION_TYPE", "to": "Entity B"},
  {"from": "Entity B", "relation": "DEPENDS_ON", "to": "Entity C"}
]'
```

**For a URL:**
1. Fetch and print the clean text (arxiv abstract pages auto-redirect to PDF):
```bash
python graph/fetch_cli.py "https://arxiv.org/abs/2105.00188"
```
2. Read the output, extract all meaningful entities and relationships
3. Write them all at once with `remember_batch_cli.py` as above

**Extraction rules:**
- Entities: concrete nouns, concepts, people, systems, components, algorithms
- Relations: ALL_CAPS_UNDERSCORES — CAUSES, DEPENDS_ON, HAS_COMPONENT, EXTENDS, IS_A, USED_BY, GOVERNS, etc.
- Only extract clear, explicit relationships — not vague associations
- Use consistent entity names (same concept = same name every time)
- Be thorough — extract as many valid triples as you can find in the text

After writing, explore what was added:
```bash
python graph/query_cli.py --seeds "Entity A,Entity B"
```

### Mode 2: API-powered extraction (Haiku extracts, requires Anthropic API credits)

```bash
# From a URL (arxiv abstract pages are automatically redirected to PDF)
python graph/ingest_cli.py --url "https://arxiv.org/abs/2105.00188"

# From a local file
python graph/ingest_cli.py --file path/to/document.pdf
python graph/ingest_cli.py --file path/to/document.txt

# From raw text
python graph/ingest_cli.py --text "The ripple matrix governs propagation..."
```

Use this when credits are available and the document is large (many chunks benefit from parallel Haiku extraction).

---

## Memory update — do this after EVERY response

After answering any question or completing any task, always do this:

1. Review what you just reasoned over — the graph edges, any fetched content, any new connections you noticed
2. Identify relationships that are **new and not already in the graph**
3. If you found any, write them immediately:

```bash
python graph/remember_batch_cli.py '[
  {"from": "Entity A", "relation": "RELATION_TYPE", "to": "Entity B"},
  {"from": "Entity C", "relation": "EXTENDS", "to": "Entity D"}
]'
```

If you found nothing new, skip this step — don't write duplicates.

This is how the graph grows with use. Every session should leave the graph slightly smarter than it was.

**Rules:**
- Only commit facts directly supported by content you've read — not speculation
- Do not connect entities from different domains unless an explicit link exists
- Do not duplicate facts already present in the graph
- Use ALL_CAPS_UNDERSCORES for relation types

---

## Resolving duplicate entities

```bash
python main.py resolve           # merge duplicate nodes
python main.py resolve --dry-run # preview without touching the graph
```

---

## Graph schema

Nodes: `(:Entity {id, name, type})`
Edges: `-[:RELATION {type, weight, session_id, created_at}]->`

Entity IDs are deterministic `uuid5(name.lower())` — same concept across documents = same node.
Facts written via `remember_cli.py`, `remember_batch_cli.py`, and `ingest_cli.py` are tagged `session_id="claude-code"`.

---

## Project structure

```
graph/query_cli.py          ← read: retrieve subgraph for questions
graph/fetch_cli.py          ← fetch: get clean text from a URL (no extraction)
graph/remember_cli.py       ← write: commit one fact to permanent memory
graph/remember_batch_cli.py ← write: commit many facts at once (JSON array)
graph/ingest_cli.py         ← write: API-powered fetch + extract + store
query/agentic_agent.py      ← full agentic mode (python main.py query --agentic "...")
ingestion/                  ← document ingestion pipeline
graph/neo4j_client.py       ← all Neo4j I/O
```

---

## Workflow summary

| Goal | Zero API cost | With API credits |
|---|---|---|
| Answer a question | `query_cli.py` → reason | `query_cli.py` → reason |
| Ingest a file | Read file → extract → `remember_batch_cli.py` | `ingest_cli.py --file` |
| Ingest a URL | `fetch_cli.py` → extract → `remember_batch_cli.py` | `ingest_cli.py --url` |
| Save a discovered fact | `remember_cli.py` or `remember_batch_cli.py` | same |
| Clean up duplicates | `python main.py resolve` | same |
