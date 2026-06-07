# GraphRAG — Persistent Memory for Claude Code

Claude Code forgets everything when a session ends. GraphRAG gives it a memory that persists across every session, every project, and every machine.

It works as two layers that run automatically:

- **File memory** (`memory/`) — markdown files injected into Claude at the start of every session. Contains project context, design decisions, and learnings that accumulate over time.
- **Knowledge graph** (Neo4j) — structured facts stored as typed relationships between entities. Covers both document knowledge (papers, notes, architecture docs) and code structure (files, functions, dependencies).

When you open Claude Code in this project, it already knows what you've built, what decisions you've made, and how your code is wired together — without you having to explain it again.

---

## What it gives you

**Automatic context at session start**
Every session begins with the contents of `memory/` injected as context. Claude knows your project before you type your first message.

**Session metadata logged automatically**
Every session close writes a lightweight entry to `memory/session_log.md` — timestamp, session ID, and files changed. When you're ready to save what you learned, say **"store my session"** and Claude extracts the key insights natively, with no API cost.

**Code graph always in sync**
Every file you save is automatically re-ingested into the code graph. Claude always knows the current dependencies, call chains, and structure of your codebase — even mid-session.

**46% fewer tokens on code tasks**
Because Claude navigates directly to the right files instead of exploring blindly, tasks that would normally require reading 3–4 files to orient only require reading 1–2. Measured across realistic edit tasks.

---

## How memory works

### Layer 1 — File memory (zero cost, always on)

```
memory/
  project.md       project overview, architecture, core value
  components.md    every script and hook, how to use them
  decisions.md     design rules accumulated over time
  learnings.md     session-by-session learnings, auto-appended
```

These files are in the repository. Anyone who clones gets the accumulated context immediately. The `SessionStart` hook injects them automatically — no setup needed beyond cloning.

Learnings grow in two ways:
- **Automatic** — every session close logs metadata to `session_log.md` (timestamp, session ID, files changed)
- **On demand** — say **"store my session"** before closing and Claude writes distilled insights to `learnings.md` natively, zero API cost

You can also write directly to any `memory/` file at any time.

### Layer 2 — Knowledge graph (Neo4j)

Two separate graphs:

**Doc graph** — concepts extracted from papers, documents, architecture notes, and URLs. Stored as typed relationships: `(Entity A) -[:RELATION]-> (Entity B)`. Query it with natural language — no API cost.

```bash
python graph/query_cli.py "how does seed finding work?" --hops 2
```

**Code graph** — file structure, imports, function calls, and dependencies for any ingested codebase. Always up to date because every file save triggers re-ingestion.

```bash
python -m graph.code_query_cli --deps graph/query_cli.py --project graphrag --plain
python -m graph.code_query_cli --impact "Neo4jClient" --project graphrag --plain
```

---

## Setup

### Prerequisites
- Python 3.10+
- Neo4j (Desktop, Docker, or AuraDB — see below)
- Claude Code CLI installed

### Neo4j — pick one

**Docker (fastest)**
```bash
docker run --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password neo4j:latest
```

**Neo4j Desktop**
Download from [neo4j.com/download](https://neo4j.com/download), create a local DBMS, start it.

**AuraDB (cloud, free tier)**
Sign up at [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura).

### Install

```bash
git clone <repo>
cd graphrag
./install.sh
```

`install.sh` installs Python dependencies, creates `.env` from the template, verifies the Neo4j connection, and ingests the codebase into the code graph. The doc graph starts empty and grows as you work.

### Configure `.env`

```
ANTHROPIC_API_KEY=your_key_here
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

### Register with Claude Code globally (optional but recommended)

To make the knowledge graph available from **any directory** — not just this one — add it to your global Claude Code config:

```bash
cat >> ~/.claude/CLAUDE.md << 'EOF'

# Persistent Knowledge Graph (GraphRAG)

A Neo4j knowledge graph stores persistent memory across all sessions.
Project root: /path/to/graphrag

ALWAYS query the knowledge graph first before answering any question:
```bash
cd /path/to/graphrag && python graph/query_cli.py "your question here"
```

Full instructions: /path/to/graphrag/CLAUDE.md
EOF
```

---

## Using it

### Ask questions (free, no API cost)

```bash
claude  # open Claude Code in this directory
```

Claude automatically queries the graph before answering. You don't need to run any commands — just ask.

### Add a document to memory

```bash
# From a local file
python graph/ingest_cli.py --file path/to/paper.pdf

# From a URL
python graph/ingest_cli.py --url "https://arxiv.org/abs/2105.00188"
```

The document is chunked, entities and relationships are extracted, and everything is written to Neo4j permanently. Future sessions can query it.

**Zero-cost alternative (no API credits):** read the file yourself and write the triples directly:

```bash
python graph/remember_batch_cli.py '[
  {"from": "Concept A", "relation": "CAUSES", "to": "Concept B"},
  {"from": "System X", "relation": "DEPENDS_ON", "to": "System Y"}
]'
```

### Add a codebase to the graph

```bash
python main.py ingest-code /path/to/repo --project myproject --skip-normalize
```

After this, Claude can answer questions about that codebase's structure without reading files:

```bash
python -m graph.code_query_cli --tree myproject --plain
python -m graph.code_query_cli --deps src/auth/login.py --project myproject --plain
python -m graph.code_query_cli --impact "authenticate" --project myproject --plain
```

### Save a fact mid-session

```bash
python graph/remember_cli.py "entity_resolver" "USES" "Claude Haiku"
```

### Clean up duplicate entities

```bash
python main.py resolve
```

---

## What runs automatically

| Hook | When | What it does |
|---|---|---|
| `SessionStart` | Every session opens | Reads `memory/*.md`, injects as context |
| `Stop` | Every session ends | Logs metadata (timestamp, session ID, files changed) to `session_log.md` |
| `PostToolUse` (Write/Edit) | Every file save | Re-ingests the changed file into the code graph |

All three are wired in `.claude/settings.json` — they run without any action from you.

---

## Project structure

```
graphrag/
├── memory/                     file-based memory (auto-loaded each session)
│   ├── project.md
│   ├── components.md
│   ├── decisions.md
│   ├── learnings.md            grows when you say "store my session"
│   └── session_log.md          auto-logged metadata on every session close
├── graph/
│   ├── query_cli.py            query doc graph (zero cost)
│   ├── code_query_cli.py       query code graph (deps/impact/trace/tree)
│   ├── remember_cli.py         write one fact to graph
│   ├── remember_batch_cli.py   write many facts at once
│   ├── ingest_cli.py           ingest PDF/URL into doc graph
│   ├── nav_agent.py            routes task text to the right graph tool
│   ├── neo4j_client.py         doc graph Neo4j I/O
│   ├── code_graph_client.py    code graph Neo4j I/O
│   └── db_router.py            routes to master/project/auto database
├── ingestion/
│   ├── code_parser.py          tree-sitter extraction (no API)
│   ├── hierarchy_builder.py    builds Project→Folder→File skeleton
│   ├── file_watcher.py         incremental updates on file change
│   ├── entity_resolver.py      merges duplicate entities
│   └── reader_agent.py         Haiku-powered extraction from text chunks
├── scripts/
│   ├── session_start.py        SessionStart hook — loads memory/
│   ├── auto_memory.py          Stop hook — logs session metadata to session_log.md
│   └── on_file_change.py       PostToolUse hook — syncs code graph
├── agents/
│   ├── ROUTING.md              when to use which graph tool
│   ├── CODE.md                 code graph operations
│   ├── CONCEPT.md              doc graph operations
│   ├── HYBRID.md               cross-graph (doc ↔ code) operations
│   └── INGEST.md               adding knowledge to the graph
├── main.py                     CLI: ingest, ingest-code, query, resolve
├── CLAUDE.md                   instructions Claude reads when in this project
├── install.sh                  one-command setup for new clones
└── .claude/settings.json       hook configuration
```

---

## The memory loop

```
Clone repo
    ↓
./install.sh  (deps + Neo4j check + code graph ingest)
    ↓
claude  (SessionStart hook loads memory/ automatically)
    ↓
Work — ask questions, edit files, ingest docs
    ↓
File edits → on_file_change.py → code graph stays in sync
    ↓
"store my session" → Claude writes learnings to memory/learnings.md (zero API cost)
    ↓
Session ends → auto_memory.py → timestamp + files logged to session_log.md
    ↓
Next session → memory/ injected again, graph has new facts
    ↓
Graph grows smarter with every session
```

---

## Why a graph instead of a vector store

Vector stores retrieve similar chunks. A knowledge graph retrieves structured facts and lets you follow typed relationships across them.

This means Claude can:
- **Follow reasoning chains** — not just find similar text, but traverse `A CAUSES B DEPENDS_ON C`
- **Connect concepts across documents** that never explicitly reference each other
- **Know your code structure** — what calls what, what imports what, where things live
- **Write back new facts** — the graph gets smarter as you use it, not just as you ingest
- **Navigate without exploring** — go directly to the right file instead of reading several wrong ones first
