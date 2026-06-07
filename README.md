# GraphRAG — Persistent Memory for LLMs

A knowledge graph system that gives LLMs persistent, structured memory. Documents are ingested into a Neo4j graph as entities and relationships. An agentic query layer lets the model traverse that memory, write new facts it discovers, and pull in new sources — all within a single session.

---

## What it does

Most LLMs forget everything when the context window resets. This system gives the model a graph it can read from and write to across sessions. Every fact lives in Neo4j as a typed relationship between named entities. The model navigates this graph using tools, reasons over what it finds, and commits new knowledge back — making the graph smarter with every session.

---

## Setup

### 1. Prerequisites

- **Python 3.10+** — check with `python --version`
- **Neo4j** — the graph database that stores all memory (pick one option below)
- **Anthropic API key** — get one at [console.anthropic.com](https://console.anthropic.com) → API Keys

### 2. Neo4j — pick one option

**Option A: Neo4j Desktop (easiest, local)**
1. Download from [neo4j.com/download](https://neo4j.com/download)
2. Create a new project → Add → Local DBMS
3. Set a password, then click Start
4. Default URI: `bolt://localhost:7687`

**Option B: Docker (no install)**
```bash
docker run \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:latest
```

**Option C: AuraDB (cloud, free tier available)**
1. Sign up at [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura)
2. Create a free instance — you'll get a URI, username, and password

### 3. Install dependencies

```bash
git clone https://github.com/your-username/graphrag
cd graphrag
pip install anthropic neo4j python-dotenv PyPDF2 rich tqdm
```

### 4. Configure environment

Create a `.env` file in the project root:
```
ANTHROPIC_API_KEY=your_key_here
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

> For AuraDB, use the URI from your instance dashboard (starts with `neo4j+s://`).

### 5. Verify the connection

```bash
python graph/query_cli.py --list-nodes
```

If Neo4j is running and credentials are correct, you'll see `0 nodes in graph:` (empty graph is fine — you haven't ingested anything yet). If you see a connection error, check that Neo4j is started and your `.env` password matches.

### 6. First run

Ingest a document and ask a question:

```bash
# Ingest a PDF or text file
python main.py ingest path/to/your_document.pdf

# Ask a question (no API credits needed)
cd /path/to/graphrag && claude
# Then ask: "What does the document say about X?"

# Or run the agentic mode directly
python main.py query --agentic "What are the main concepts in the document?"
```

---

## Two ways to use it

| Mode | Cost | Read | Write facts | Ingest sources |
|---|---|---|---|---|
| **Claude Code CLI** | $0 for reads | ✅ | ✅ | ✅ |
| **Agentic (`--agentic`)** | API credits | ✅ | ✅ | ✅ |

Both modes give you full persistent memory. Claude Code uses explicit CLI scripts. Agentic mode drives everything autonomously via tools.

---

## Claude Code CLI (recommended, zero read cost)

Open Claude Code in the project directory and interact naturally. Claude Code automatically uses the graph tools below.

```bash
cd /path/to/graphrag
claude
```

### Reading the graph
```bash
python graph/query_cli.py "What is ripple propagation?"
python graph/query_cli.py "question" --hops 3          # deeper traversal
python graph/query_cli.py --seeds "Ripple Propagation,BKT"  # specific seeds
python graph/query_cli.py --list-nodes                 # see everything in the graph
```

Claude Code runs this automatically for any question, then reasons over the returned edges natively — no API credits consumed.

### Ingesting new sources (persists to graph)
```bash
# From a URL — arxiv abstract pages are auto-redirected to PDF
python graph/ingest_cli.py --url "https://arxiv.org/abs/2105.00188"

# From a local file
python graph/ingest_cli.py --file path/to/paper.pdf
python graph/ingest_cli.py --file path/to/notes.txt

# From raw text
python graph/ingest_cli.py --text "The ripple matrix governs propagation across..."
```

Chunks the content, extracts entities and relationships using Claude Haiku, writes everything to Neo4j permanently. Claude Code then immediately explores the new nodes.

### Writing facts to memory (persists to graph)
```bash
python graph/remember_cli.py "Entity A" "RELATION_TYPE" "Entity B"

# Examples:
python graph/remember_cli.py "Ripple Matrix" "GOVERNS" "Ripple Propagation"
python graph/remember_cli.py "BKT" "IS_A" "Bayesian Knowledge Tracing"
python graph/remember_cli.py "Slot Model" "DEPENDS_ON" "Forgetting Curve"
```

When Claude Code discovers a new relationship while reasoning over graph data, it calls this to commit it permanently — tagged so it's distinguishable from ingested facts.

### Typical Claude Code session
Just ask naturally — Claude Code handles the tool calls:

```
"What is ripple propagation?"
→ runs query_cli.py, reasons over edges, answers

"Ingest this paper: https://arxiv.org/abs/2105.00188"
→ runs ingest_cli.py, writes to graph, explores new nodes

"How does this paper relate to what's already in the graph?"
→ runs query_cli.py with seeds from both sources, finds connections

"Save that connection"
→ runs remember_cli.py to commit the relationship permanently
```

---

## Agentic mode (autonomous, API credits)

The model drives everything itself using tools — traversal, write-back, and mid-session ingestion happen automatically without you specifying commands.

```bash
python main.py query --agentic "What is ripple propagation?"
```

### How it works

**1. Seed finding**
The full list of node names is fetched from Neo4j and shown to Haiku alongside the query. Haiku picks 2–5 starting nodes from the real graph vocabulary — no hallucinated entity names.

**2. Haiku traversal loop**
Haiku drives graph exploration using three tools:

**`get_neighbours(node_names)`**
Fetches all direct neighbours for a batch of 8–12 nodes in one Neo4j query. A visited set prevents re-exploring the same node twice. When Haiku decides to stop, a confirmation gate fires: it's shown all nodes that appeared during traversal but weren't explored yet, and asked to confirm it has enough. This continues until Haiku is genuinely done.

**`remember(from_entity, relation_type, to_entity)`**
Commits a new fact to the graph. Before writing, a validation step checks that the fact is directly supported by edges already seen in the current traversal — speculative cross-domain inferences are rejected. Accepted facts are tagged with the session ID and persist across future sessions.

**`ingest_source(source, source_type)`**
Pulls in new knowledge mid-session. Pass a URL (`source_type: "url"`) or raw text (`source_type: "text"`). The system fetches, chunks, extracts triples, and writes them to the graph. Haiku receives the new node names and can immediately explore them with `get_neighbours`. Each URL is only fetched once per session — duplicate ingest calls are blocked.

**3. Traversal confirmation gate**
When Haiku signals it's done, the system shows it all nodes that appeared during traversal but weren't explored yet. Haiku gets one chance to reconsider — if it picks more nodes, the loop continues; if it stops again, synthesis begins.

**4. Sonnet synthesis**
All edges collected during traversal are sent to Claude Sonnet in a single call with extended thinking enabled. Sonnet produces a grounded, prose answer. Every claim must trace to a specific edge in the collected subgraph. Both the thinking trace and the answer stream to the terminal in real time.

**5. Output**
- Live status during traversal: `[9] exploring: Ripple Matrix, GRU update, Ripple-Propagated Updates`
- `[memory] wrote: (A) --[REL]--> (B)` when a fact passes validation and is committed
- `[memory] rejected: ...` when a proposed fact isn't grounded in the current edges
- `[ingest] arxiv detected — fetching PDF: ...` when a paper URL is resolved to its PDF
- `[ingest] 12 chunks — extracting triples...` as extraction progresses
- `[confirming — N unexplored nodes available]` when the confirmation gate fires
- Thinking block streamed as Sonnet reasons
- Final answer streamed token by token
- Traversal path table showing every node explored
- Summary: nodes explored, facts written, sources ingested, time taken

---

## Other commands

### Bulk document ingestion
```bash
python main.py ingest path/to/document.pdf
python main.py ingest path/to/document.txt
```
Chunks the document into 800-character windows, extracts entities and relationships using Claude Haiku in parallel, and writes them to Neo4j. Idempotent — safe to re-run.

### BFS query (fast, no synthesis)
```bash
python main.py query "What is ripple propagation?"
```

### Full graph in context
```bash
python main.py query --full-graph "What is ripple propagation?"
```

### Resolve duplicate entities
```bash
python main.py resolve           # merge duplicates
python main.py resolve --dry-run # preview without touching the graph
```
Finds entity names that refer to the same concept (e.g. "BKT" and "Bayesian Knowledge Tracing") and merges them into a single node, re-pointing all relationships.

---

## The memory loop

```
Ingest documents / URLs / text
          ↓
       Neo4j graph  ←──────────────────────────────────────┐
          ↓                                                 │
    Seed finding (picks entry points)                       │
          ↓                                                 │
    Traversal loop                                          │
      ├── get_neighbours / query_cli  → read memory         │
      ├── remember / remember_cli     → write new facts ────┤
      └── ingest_source / ingest_cli  → fetch + write ──────┘
          ↓
    Synthesis (grounded answer)
          ↓
    Streamed answer
```

Facts written via `remember` / `remember_cli` and triples ingested via `ingest_source` / `ingest_cli` are tagged with session ID, so they're distinguishable from bulk-ingested content and can later be scoped, aged, or removed independently.

---

## Quality controls

**Ingestion — clean source fetching**
For arxiv URLs, the system redirects from the abstract HTML page to the PDF and extracts text with PyPDF2, avoiding navigation menus, citation widgets, and HTML noise. Generic URLs fall back to HTML tag stripping.

**Ingestion — entity name normalisation**
Entity names are normalised during extraction: internal whitespace is collapsed, trailing punctuation is stripped, and IDs are computed from the lowercase form. This prevents the same concept appearing as multiple nodes due to minor formatting differences (e.g. `"Stochastic Matrices"` and `"Stochastic matrices"` resolve to the same node).

**Remember — grounding validation (agentic mode)**
Before any fact is written to permanent memory in agentic mode, a Haiku validation call checks that the fact is directly and explicitly supported by the graph edges seen in the current traversal — not merely plausible or inferred across domains. Rejected facts are returned to Haiku with an explanation.

**Synthesis — grounding requirement**
The synthesis prompt requires every claim to trace to a specific edge in the collected subgraph. Cross-domain connections are forbidden unless an explicit edge links the domains. If the graph doesn't contain enough information, Sonnet is instructed to say so rather than speculate.

**Post-ingestion — entity resolution**
`python main.py resolve` runs a Haiku pass over all node names, clusters duplicates (same concept under different names or casing), and merges them — re-pointing all relationships to the canonical node.

---

## Query modes compared

| Mode | When to use | How it works | API credits |
|---|---|---|---|
| Claude Code (`query_cli.py`) | Questions, zero read cost | Keyword BFS → Claude Code reasons natively | None |
| Claude Code (`ingest_cli.py`) | Add new documents / URLs | Haiku extraction → writes to Neo4j | Haiku only |
| Claude Code (`remember_cli.py`) | Save a discovered fact | Direct Neo4j write | None |
| `--agentic` | Complex multi-hop, autonomous | Haiku traverses + Sonnet synthesizes | Yes |
| `--full-graph` | Small graphs, broad questions | Entire graph in one Sonnet call | Yes |
| Default (BFS) | Fast lookups | BFS with Haiku scoring each layer | Yes |

---

## Architecture

```
main.py
├── ingestion/
│   ├── chunker.py          sliding window text splitter (800 chars, 100 overlap)
│   ├── reader_agent.py     Haiku extraction → triples, parallel, with prompt caching
│   ├── graph_writer.py     MERGE triples into Neo4j with session_id + created_at
│   └── entity_resolver.py  Haiku duplicate detection + Neo4j merge
├── query/
│   ├── agentic_agent.py    Haiku traversal loop + remember validation + Sonnet synthesis
│   ├── seed_finder.py      ground seed selection in real graph vocabulary
│   ├── agent.py            BFS traversal mode
│   ├── graph_context_agent.py  full-graph mode
│   ├── navigator_agent.py  BFS frontier management
│   ├── relevance_filter.py Haiku scoring for BFS mode
│   └── answer_agent.py     answer generation for BFS mode
├── graph/
│   ├── neo4j_client.py     all Neo4j I/O (read, write, remember, merge nodes)
│   ├── query_cli.py        zero-cost BFS retrieval for Claude Code
│   ├── remember_cli.py     persistent write-back for Claude Code
│   └── ingest_cli.py       persistent source ingestion for Claude Code
└── models/
    └── types.py            Entity, Relation, Triple, TraversalStep, QueryResult
```

### Models used
| Task | Model |
|---|---|
| Triple extraction (ingestion) | claude-haiku-4-5 |
| Seed selection | claude-haiku-4-5 |
| Graph traversal | claude-haiku-4-5 |
| Remember validation | claude-haiku-4-5 |
| Entity resolution | claude-haiku-4-5 |
| Answer synthesis | claude-sonnet-4-6 (extended thinking) |

### Neo4j schema
```
(:Entity {id, name, type})
  -[:RELATION {type, weight, description, session_id, created_at, source}]->
(:Entity)
```

- `id` — deterministic `uuid5(name.lower())` — same entity across documents gets the same node
- `session_id` — `"ingestion"` for bulk-ingested facts; `"claude-code"` for Claude Code writes; UUID of the agent run for agentic session facts
- `source` — `"agent"` for facts written by the `remember` tool or `remember_cli.py`

---

## What makes this different from plain RAG

Plain RAG chunks documents and retrieves the most similar chunks to a query. It can only find what's explicitly written.

This system extracts the *structure* of knowledge — entities and typed relationships — and stores it as a graph. The model can:

- **Follow chains of reasoning** across the graph, not just retrieve flat chunks
- **Connect concepts across documents** that never explicitly reference each other
- **Write back** new facts it discovers — the memory grows with use
- **Ingest new sources on demand** — papers from arxiv, web pages, or raw text, mid-session
- **Validate before writing** — facts must be grounded in actual graph edges before entering permanent memory
- **Deduplicate** entities that appear under different names across sources
- **Work from Claude Code with full persistence** — read, write, and ingest without leaving the CLI
