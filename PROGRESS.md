# CodeCompass — Progress & Roadmap

## Goal

Build a **memory layer for LLMs** — a persistent, structured knowledge store that any model can read from and write to across sessions. The graph captures entities and relationships extracted from documents; the agentic query layer lets a model traverse and reason over that memory on demand.

---

## What We Built (v2.0 — opencode Integration)

### MCP Server (`graph/mcp_server.py`) ✅
Exposes the code graph as 8 native MCP tools available from any working directory:
- `list_projects`, `blast_radius`, `impact`, `deps`, `trace`, `tree`, `styles`, `batch_impact`
- Uses existing `CodeGraphClient` — same Neo4j queries, zero code duplication
- Returns plain text with stale-index warnings

### opencode Plugin (`opencode/plugins/memory.ts`) ✅
Replaces old Claude Code hooks with opencode-native equivalents:
- `session.compacting` — injects learnings context into compaction prompt
- `session.compacted` — writes learnings placeholder to `memory/learnings.md`
- `session.idle` — logs session metadata to `memory/session_log.md`
- Helper scripts at `opencode/scripts/log_session.py` and `save_learnings.py`

### Instructions (`opencode/instructions.md`) ✅
Loaded into every opencode session via `instructions` config:
- Mandates graph-first behavior: always query before editing
- Maps scenarios to tools (blast_radius first, impact for renames, etc.)
- Reference table for all 8 MCP tools

### One-Command Setup (`install.sh`) ✅
Updated to auto-configure opencode:
- Installs MCP SDK alongside existing deps
- Writes `~/.config/opencode/opencode.json` with MCP + instructions + plugin paths
- Updates plugin with real filesystem paths
- Safe merge — writes to `.codecompass.json` first, user copies to activate

### AGENTS.md Auto-Registration ✅
`ingest-code` now writes to `AGENTS.md` (opencode convention) instead of `CLAUDE.md`.

---

## What We Built (v1.x)

### Ingestion Pipeline
- **PDF/text → chunks → triples → Neo4j**
- PyPDF2 extracts full text; sliding window chunker splits into 800-char chunks with 100-char overlap
- Each chunk sent to **Claude Haiku** for entity + relationship extraction (JSON)
- 5 chunks processed concurrently via `asyncio.Semaphore`
- Triples written to Neo4j with `MERGE` (idempotent — safe to re-run)
- Entity IDs are deterministic (`uuid5(name.lower())`) so the same entity across chunks gets the same node

### Three Query Modes

| Mode | Command | How it works |
|---|---|---|
| Traversal | `python main.py query "..."` | BFS with Haiku scoring per frontier layer |
| Full graph | `python main.py query --full-graph "..."` | Entire graph sent to Sonnet in one cached call |
| **Agentic** | `python main.py query --agentic "..."` | Haiku drives tool-use traversal, Sonnet synthesizes |

### Agentic Mode (the good one)

**Seed finding**
- Fetches all node names from Neo4j
- Shows them to Haiku alongside the query — picks from real graph vocabulary, no hallucinated entity names

**Traversal loop (Haiku)**
- Tool: `get_neighbours(node_names: list)` — batches 3–5 nodes per call
- One Neo4j query per tool call handles all nodes in the batch
- Visited set prevents re-exploration
- Confirmation gate: when Haiku wants to stop, it's shown unexplored candidate nodes and asked to confirm — fires until Haiku is genuinely done

**Three-tool memory loop**
- `get_neighbours` — read existing memory (batched, 3–5 nodes per call)
- `remember` — write a new inferred fact back to the graph, tagged with session_id
- `ingest_source` — pull in a URL or raw text mid-session, chunk + extract + write to graph, then continue exploring the new nodes immediately — closes the read/write/ingest loop

**Answer synthesis (Sonnet + extended thinking)**
- All collected edges sent to Sonnet in a single call
- Extended thinking enabled (`budget_tokens: 5000`) via `betas=["interleaved-thinking-2025-05-14"]`
- Thinking and answer both streamed to terminal as tokens arrive
- No hard cap on traversal — Haiku explores until it is genuinely done

**Performance after optimisations**
- Before batching: ~17 sequential Haiku turns → ~50s traversal
- After batching: ~7 batch turns → ~14s traversal

### Output
- Live status: `[3] exploring: Ripple Propagation, Slot 0, Ripple Matrix`
- Traversal table showing every node explored
- Streamed answer grounded in actual graph relationships (`X UPDATES Y`, `X DECOUPLED_FROM Y`)

---

## What We Can Do Next

Everything below is ordered by how directly it advances the **LLM memory** goal.

### Core memory capabilities

**1. Write-back from model** ✅
`remember(from_entity, relation_type, to_entity)` tool added alongside `get_neighbours`. Haiku can commit new facts mid-session. Facts are written to Neo4j immediately, tagged with `session_id` and `source: agent`.

**2. Session-scoped memory** ✅
Every relationship in Neo4j now carries `session_id` and `created_at`. Ingested facts are tagged `session_id: "ingestion"`; agent-written facts carry the UUID of the run that created them. Foundation for recency weighting, per-user namespacing, and selective forgetting.

**3. Entity resolution / deduplication** ✅
`python main.py resolve` runs a post-ingestion Haiku pass over all node names, clusters duplicates, and merges them — re-pointing all relationships to the canonical node and deleting duplicates. `--dry-run` flag shows what would be merged without touching the graph.

**4. Multi-document ingestion**
The graph's advantage over plain RAG is cross-document entity linking. Ingesting 10–20 documents from different sources lets the model draw connections none of the source documents make explicitly — the graph becomes more valuable than any single document.

### Quality & reliability

**5. Ingestion quality validation**
Haiku extraction is lossy and silent about it. After ingestion, sample N triples and ask Sonnet to verify them against the source chunk. Flag and optionally re-extract bad triples.

**6. Incremental ingestion**
Re-ingesting a document currently re-extracts everything. Track processed chunks by hash and skip them on subsequent runs — makes ingestion safe to re-run as new documents arrive.

**7. Better seed ranking**
The seed finder returns up to 5 nodes with no ranking. Ask Haiku to rank candidates by relevance. Top 3 ranked seeds > 5 unranked seeds.

### Performance

**8. Prompt caching on the Sonnet synthesis call**
The edge list sent to Sonnet is identical across queries until re-ingestion. Adding `cache_control: ephemeral` to that block cuts synthesis cost ~10× after the first query.

**9. Subgraph result caching**
Cache edges returned for frequently-explored nodes. If the same node appears in 10 queries, the Neo4j call is redundant after the first.

### Interfaces

**10. REST API / web UI**
Wrap `run_agentic_agent` in a FastAPI endpoint. Stream the answer over SSE. Required for any integration beyond the terminal (chat UI, IDE plugin, etc.).

**11. MCP server for code graph** ✅
Code graph queries exposed as native MCP tools (blast_radius, impact, deps, etc.). Available from any working directory. Config auto-generated by install.sh.

**12. Graph visualisation**
Export the traversal path as a Cypher subgraph and render it in Neo4j Browser or D3. Shows which memory nodes the model used to reach its answer.

**13. Publish as reusable MCP package**
Package `graph/mcp_server.py` as a standalone `codecompass-mcp` Python package on PyPI so any MCP-compatible agent can install it without cloning the full repo.
