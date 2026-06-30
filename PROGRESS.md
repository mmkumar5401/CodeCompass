# CodeCompass — Progress & Roadmap

## Goal

Build a **structural code context layer for AI coding agents** — a persistent, local knowledge graph that an agent can traverse to understand what's connected before making any change.

---

## What We Built (v2.1 — Local Graph)

### Local Graph Engine (`graph/local_graph_client.py`) ✅
Replaced Neo4j with NetworkX + JSON persistence:
- `LocalGraphClient` reads/writes `.codecompass/graph.json` using `nx.node_link_data` / `nx.node_link_graph`
- Typed relationship edges: `CALLS`, `IMPORTS`, `INHERITS`, `DEFINED_IN`, `HAS_CLASS`, `POSTS_TO`, `INCLUDES`, `STYLES`, `USED_BY`, `USES_VAR`, `REFERENCES`
- Corrupted `graph.json` is caught on load and regenerated from scratch
- `get_client()` factory in `code_graph_client.py` returns `LocalGraphClient` — callers unchanged

### `codecompass init` command ✅
- Creates `.codecompass/` with stub files: `graph.json`, `memory.md`, `learnings.md`
- Safe to re-run — skips existing files
- `ingest-code` runs it automatically if `.codecompass` is missing

### Simplified CLI ✅
- No `--project` flag — project name inferred from directory basename
- Commands: `init`, `ingest-code`, `load-triples`, `watch`, `setup`

### Setup Wizard (`graph/setup.py`) ✅
- `codecompass setup` writes all opencode config files to `~/.config/opencode/codecompass/`
- Prints the JSON block to merge into `opencode.json`

---

## What We Built (v2.0 — opencode Integration)

### Query CLI (`graph/code_query_cli.py`) ✅
Exposes all graph traversals as bash commands the agent runs directly:
- `--blast-radius`, `--impact`, `--deps`, `--trace`, `--tree`, `--styles`, `--batch-impact`
- Returns plain text with stale-index warnings

### Instructions (`opencode/instructions.md`) ✅
Loaded into every opencode session via `instructions` config:
- Mandates graph-first behavior: always query before editing
- Maps scenarios to tools

### AGENTS.md Auto-Registration ✅
`ingest-code` writes a `## Code graph` block into the target project's `AGENTS.md`.

---

## What We Built (v1.x — Agentic Memory / Document Graph)

### Ingestion Pipeline
- PDF/text → chunks → triples → graph
- PyPDF2 + sliding-window chunker (800-char / 100-char overlap)
- Claude Haiku for entity + relationship extraction (5 concurrent chunks)
- Triples written with MERGE (idempotent), deterministic entity IDs via `uuid5`

### Three Query Modes
| Mode | How it works |
|---|---|
| Traversal | BFS with Haiku scoring per frontier layer |
| Full graph | Entire graph sent to Sonnet in one cached call |
| **Agentic** | Haiku drives tool-use traversal, Sonnet synthesizes |

### Agentic Mode
- Seed finding via all node names shown to Haiku
- Batched `get_neighbours(node_names)` — 3–5 nodes per call, one graph lookup
- Write-back: `remember(from, rel, to)` commits new facts mid-session
- `ingest_source` pulls in a URL mid-session, chunks + extracts + continues exploring
- Synthesis via Sonnet with extended thinking (`budget_tokens: 5000`)
- Before batching: ~17 turns / ~50s. After: ~7 turns / ~14s

---

## What We Can Do Next

Ordered by how directly it advances the core JTBD (make complete, confident changes).

### High priority

**1. Git diff integration** — `blast_radius` over `git diff --name-only HEAD` output. Agent gets the full impact of staged changes before committing. Direct JTBD fit.

**2. Language expansion** — Go, Java, Rust parsers. Opens the tool to backend-heavy teams. Each language is ~30 RICE.

**3. Performance benchmark** — Validate the < 500ms 3-hop traversal target for 5,000-node graphs. Establish a regression test so graph growth doesn't silently slow queries.

### Medium priority

**4. Ingestion quality validation** — Sample N triples post-ingest and ask Sonnet to verify against source chunks. Flag bad extractions.

**5. Incremental ingestion** — Track processed chunks by hash. Skip re-extraction on re-ingest of unchanged files.

**6. Graph visualisation** — Export traversal path as JSON and render in a browser (D3 or similar). Shows which nodes the agent used to reach its answer.

### Blocked (insufficient evidence or cost)

- VS Code extension — no evidence agents need a GUI
- Cross-repo graph — XL effort, no confirmed demand
- Team / cloud sync — XL effort, no confirmed demand
- Natural language query — assumption-dependent, validate first

---

## Acceptance Criteria (local graph migration — in progress)

- [x] `codecompass init <repo_path>` creates `.codecompass/` with `graph.json`, `memory.md`, `learnings.md`
- [x] All Neo4j dependencies removed; replaced with `networkx` + JSON
- [x] `ingest-code` auto-detects `.codecompass` and updates `graph.json` without `--project`
- [ ] All traversal features (`--impact`, `--deps`, `--tree`, etc.) verified via `code_query_cli.py` on local graph
- [ ] 3-hop traversal < 500ms for 5,000-node graph
- [ ] Full test suite passing (end-to-end, empty repo, corrupted graph, cross-project isolation, scale)
