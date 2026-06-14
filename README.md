# GraphRAG — Code Dependency Index for Claude Code

Answers one question: **what should I read before editing X?**

It's a Neo4j-backed code dependency index. Ingest a repo once, then ask Claude Code which files to read before touching anything — without blindly exploring.

---

## What it does

```bash
# What does this file import (direct + transitive)?
python -m graph.code_query_cli --deps ingestion/file_watcher.py --project graphrag

# What would break if I change this function?
python -m graph.code_query_cli --impact "write_code_triple" --project graphrag

# Trace the call chain forward from an entry point
python -m graph.code_query_cli --trace "main" --project graphrag --hops 4

# Print the full folder/file hierarchy
python -m graph.code_query_cli --tree graphrag

# See all ingested projects
python -m graph.code_query_cli --list-projects
```

Output is plain text by default (agent-friendly). Add `--rich` for formatted tables.

Each result includes `# index updated: <timestamp>`. If the index is older than 24 hours a `WARNING` is printed automatically.

---

## Setup

### Prerequisites

- Python 3.10+
- Docker (for Neo4j)
- Claude Code CLI

### Start Neo4j

```bash
docker compose up -d
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure `.env`

```bash
cp .env.example .env
# Edit: set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, ANTHROPIC_API_KEY
```

### Ingest a codebase

```bash
python main.py ingest-code /path/to/repo --project <name>
```

This writes a `## Code graph` section into the project's `CLAUDE.md` automatically, so Claude Code picks up the graph context on the next session.

### Set up session memory (optional)

```bash
cp memory/learnings.example.md memory/learnings.md
```

`memory/learnings.md` is gitignored — your notes stay local. Say **"store my session"** to Claude and it will write distilled insights there automatically. The `PreCompact` hook also saves learnings before context is compressed.

---

## Commands

### `ingest-code`

```bash
python main.py ingest-code /path/to/repo --project <name>

# With Haiku LLM normalization (slower, cleans up noisy entity names)
python main.py ingest-code /path/to/repo --project <name> --normalize

# Dump raw triples to JSON for external processing
python main.py ingest-code /path/to/repo --project <name> --dump-triples /tmp/raw.json
```

### `watch`

Keep the graph live as you edit files:

```bash
python main.py watch /path/to/repo --project <name>
```

Watches for file creates, modifies, deletes, and renames. Incrementally re-ingests only changed files. Writes a PID file to `/tmp/graphrag_watcher_<project>.pid` — the query CLI warns if the watcher isn't running.

### `load-triples`

Load pre-processed triples (e.g. after external normalization):

```bash
python main.py load-triples /tmp/normalized.json --project <name>
```

---

## How it works

```
Source files
    │
    ▼
hierarchy_builder.py    — walks repo, writes Project → Folder → File skeleton
    │
    ▼
code_parser.py          — tree-sitter extraction (no API calls)
    │                     Python, JS, TS, TSX, HTML, CSS, SCSS
    ▼
Neo4j                   — typed relationships: [:CALLS], [:IMPORTS],
                          [:INHERITS], [:STYLES], [:DEFINED_IN], …
    │
    ▼
code_query_cli.py       — traversal queries: --deps, --impact, --trace,
                          --styles, --tree, --list-projects
```

Typed relationships (not generic `RELATION {type: ...}`) mean variable-length path queries are index-scannable on Neo4j Community Edition.

---

## Project structure

```
graphrag/
├── graph/
│   ├── code_graph_client.py    Neo4j I/O — nodes, edges, traversal queries
│   └── code_query_cli.py       CLI — deps / impact / trace / styles / tree
├── ingestion/
│   ├── code_parser.py          tree-sitter extraction
│   ├── hierarchy_builder.py    Project → Folder → File skeleton
│   ├── file_watcher.py         incremental updates on file change
│   └── code_normalizer.py      optional Haiku normalization pass
├── memory/
│   ├── decisions.md            architectural decisions (append-only)
│   └── learnings.md            session learnings ("store my session")
├── models/
│   └── code_types.py           CodeTriple, FileNode, FolderNode
├── scripts/
│   ├── session_start.py        SessionStart hook — loads memory/
│   ├── on_compact.py           PreCompact hook — saves learnings
│   └── on_file_change.py       PostToolUse hook — syncs code graph
├── config.py                   Neo4j config from .env
├── main.py                     CLI: ingest-code / load-triples / watch
├── CLAUDE.md                   instructions for Claude Code
├── AGENTS.md                   instructions for other agents
├── docker-compose.yml          Neo4j container
└── .claude/settings.json       hook configuration
```

---

## Automatic CLAUDE.md registration

Every `ingest-code` run writes a `## Code graph` block into the target project's `CLAUDE.md` (creating the file if it doesn't exist). The block is wrapped in HTML comment markers so re-ingesting safely updates it in place.

This means Claude Code automatically picks up the right `--project` name and query commands the next time a session opens in that directory — no manual setup.

---

## Limitations

- Structure only — the graph knows what calls what, not what anything *means*
- Supported languages: Python, JS, TS, TSX, HTML, CSS, SCSS
- External callers (consumers outside the ingested repo) won't appear in `--impact`
- If Neo4j is down, the CLI prints startup instructions instead of a traceback
- If the watcher isn't running and files were edited, the CLI warns automatically with the command to start it
