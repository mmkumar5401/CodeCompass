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

## Code graph — answering questions about a codebase

When asked anything about code structure, dependencies, call chains, or impact of a change,
query the code graph first. Do not read raw source files when the graph can answer it faster.

```bash
# What would break if I change this function?
python -m graph.code_query_cli --impact "function_name" --project <project>

# What does this file import (directly and transitively)?
python -m graph.code_query_cli --deps src/auth/login.py --project <project>

# What CSS rules style this element?
python -m graph.code_query_cli --styles "LoginForm" --project <project>

# Trace the call chain forward from an entry point
python -m graph.code_query_cli --trace "main" --project <project> --hops 4

# Print the full folder/file hierarchy
python -m graph.code_query_cli --tree <project>

# Cross-project bridges (shared schemas, API contracts)
python -m graph.code_query_cli --cross-project frontend api-service
```

**When the graph is empty or stale**, ingest first:
```bash
python main.py ingest-code /path/to/repo --project <project>
# Faster first run (skips Haiku normalization):
python main.py ingest-code /path/to/repo --project <project> --skip-normalize
```

**Keep the graph fresh while editing** — run the file watcher in a separate terminal:
```bash
python -c "
from graph import db_router
from ingestion.hierarchy_builder import build_hierarchy
from ingestion.file_watcher import FileWatcher

project = '<project>'
root = '/path/to/repo'
client = db_router.project_client(project)
file_id_map = build_hierarchy(root, project, client)
watcher = FileWatcher(root, project, client, file_id_map)
watcher.start()
"
```

---

## Project structure

```
graph/query_cli.py          ← read: retrieve subgraph for document questions
graph/code_query_cli.py     ← read: code-aware traversal (impact/deps/styles/trace/tree)
graph/fetch_cli.py          ← fetch: get clean text from a URL (no extraction)
graph/remember_cli.py       ← write: commit one fact to permanent memory
graph/remember_batch_cli.py ← write: commit many facts at once (JSON array)
graph/ingest_cli.py         ← write: API-powered fetch + extract + store
graph/code_graph_client.py  ← Neo4j client for code graphs (Project/Folder/File/Entity)
graph/db_router.py          ← routes to master / project / auto database
query/agentic_agent.py      ← full agentic mode (python main.py query --agentic "...")
ingestion/code_parser.py    ← tree-sitter extraction (local, no API)
ingestion/hierarchy_builder.py ← builds Project→Folder→File skeleton
ingestion/code_normalizer.py   ← Haiku normalization pass
ingestion/bridge_detector.py   ← cross-project BRIDGE edges
ingestion/file_watcher.py      ← incremental updates on file change
graph/neo4j_client.py       ← document graph Neo4j I/O
```

---

## Workflow summary

| Goal | Zero API cost | With API credits |
|---|---|---|
| Answer a code question | `code_query_cli.py` → reason | `code_query_cli.py` → reason |
| Answer a doc question | `query_cli.py` → reason | `query_cli.py` → reason |
| Ingest a codebase | `ingest-code --skip-normalize` | `ingest-code` (Haiku normalizes) |
| Ingest a document | Read file → extract → `remember_batch_cli.py` | `ingest_cli.py --file` |
| Ingest a URL | `fetch_cli.py` → extract → `remember_batch_cli.py` | `ingest_cli.py --url` |
| Save a discovered fact | `remember_cli.py` or `remember_batch_cli.py` | same |
| Clean up duplicates | `python main.py resolve` | same |
| Watch for file changes | `FileWatcher(...).start()` in separate terminal | same |
