# CodeCompass — Code Intelligence Engine for AI Coding Agents

[![PyPI version](https://img.shields.io/pypi/v/codecompass-mcp)](https://pypi.org/project/codecompass-mcp/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

Full-indexes an average repository in seconds, a large monorepo in minutes. Answers structural queries in under 3 seconds — *"what should I read before editing X?"*

Neo4j-backed code dependency graph. Ingest once, then opencode's MCP tools (`blast_radius`, `impact`, `deps`, `trace`, `tree`, `styles`, `batch_impact`) tell the agent exactly which files to read — no blind exploration.

---

## What's new in v2.0

| Feature | Description |
|---|---|
| PyPI package | `pip install codecompass-mcp` — works with any MCP-compatible agent |
| MCP server | Code graph exposed as native opencode tools — `blast_radius`, `impact`, `deps`, `trace`, `tree`, `styles`, `batch_impact`, `list_projects` |
| opencode plugin | Session memory auto-saves on compaction + idle |
| One-command setup | `pip install` + `codecompass ingest-code` — no clone required |
| Auto-registration | `ingest-code` writes `AGENTS.md` (opencode convention) instead of `CLAUDE.md` |

---

## What it does

Once configured, opencode has 8 native MCP tools for graph queries. The agent calls them automatically — no manual CLI needed.

```
Agent sees these tools in every session:
  list_projects  → "what repos are indexed?"
  blast_radius   → "what files will my change touch?"
  impact         → "what calls this function / uses this element?"
  deps           → "what does this file import?"
  trace          → "what's the forward call chain?"
  tree           → "show me the project structure"
  styles         → "what CSS targets this element?"
  batch_impact   → "union blast radius for a multi-file PR"
```

Instructions (loaded via `opencode/instructions.md`) mandate: **always query the graph before editing code.**

### When to use which tool

| Scenario | Tool |
|---|---|
| About to edit one file or symbol | `blast_radius` first |
| Planning a PR touching N files | `batch_impact` |
| Renaming or removing a function | `impact` |
| Understanding what a file imports | `deps` |
| Tracing a call chain forward | `trace` |
| Orienting in an unfamiliar project | `tree` |
| Finding which CSS uses a design token | `impact "token-name"` |

---

## Setup

### Prerequisites

- Python 3.10+
- Neo4j (any of the options below)
- opencode CLI

### 1. Install the package

```bash
pip install codecompass-mcp
```

### 2. Start Neo4j

Pick one:

**Docker (fastest)**
```bash
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 neo4j:5.18
```

**Docker Compose** — clone the repo and run:
```bash
git clone https://github.com/<owner>/codecompass.git
cd codecompass
docker compose up -d
```

**Neo4j Desktop** — Download from [neo4j.com/download](https://neo4j.com/download)

**AuraDB (cloud)** — [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura)

### 3. Run setup

Creates `.env`, writes instructions, plugin, and prints the opencode config:

```bash
codecompass setup
```

### 4. Ingest a codebase

```bash
codecompass ingest-code /path/to/repo --project <name>
```

This writes a `## Code graph` section into the project's `AGENTS.md` automatically.

### 5. Register with opencode

Merge the JSON that `codecompass setup` printed into `~/.config/opencode/opencode.json`:

This outputs JSON to merge into `~/.config/opencode/opencode.json`. The resulting config:

```json
{
  "instructions": ["~/.config/opencode/codecompass/instructions.md"],
  "mcp": {
    "codecompass": {
      "type": "local",
      "command": ["codecompass-mcp"]
    }
  },
  "plugin": ["~/.config/opencode/codecompass/plugins/memory.ts"]
}
```

All files are self-contained in `~/.config/opencode/codecompass/` — no repo clone needed.

### 6. Open opencode

```bash
opencode
```

Ask "what ingested projects are available?" — it should use `list_projects` to answer.

### Docker (alternative)

Prefer everything containerized? Pull the pre-built image:

```bash
docker pull ghcr.io/<owner>/codecompass:latest
docker run -d -p 8000:8000 \
  -e NEO4J_URI=bolt://<host>:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=password123 \
  ghcr.io/<owner>/codecompass:latest
```

Then configure opencode with `"type": "http", "url": "http://localhost:8000/sse"` for the MCP server. Run `codecompass setup` for instructions + plugin files.

---

## Commands

### `ingest-code`

```bash
codecompass ingest-code /path/to/repo --project <name>
codecompass ingest-code /path/to/repo --project <name> --normalize
codecompass ingest-code /path/to/repo --project <name> --dump-triples /tmp/raw.json
```

### `watch`

Keep the graph live as you edit files:

```bash
codecompass watch /path/to/repo --project <name>
```

Watches for file creates, modifies, deletes, and renames. Incrementally re-ingests only changed files. The query CLI warns if the watcher isn't running.

### `load-triples`

Load pre-processed triples (e.g. after external normalization):

```bash
codecompass load-triples /tmp/normalized.json --project <name>
```

### Direct CLI queries (bypassing the agent)

```bash
python -m graph.code_query_cli --blast-radius path/to/file.py --project <project>
python -m graph.code_query_cli --impact "FunctionName" --project <project>
python -m graph.code_query_cli --tree <project>
```

---

## Session lifecycle

```
Open opencode (any directory)
    ↓
MCP tools registered (blast_radius, impact, deps, ...) + instructions loaded
    ↓
You ask questions / make edits
    ↓
Agent queries graph via MCP tools before touching code
    ↓
Compaction fires → plugin writes learnings to memory/learnings.md
    ↓
Session idle → plugin logs metadata to memory/session_log.md
```

---

## Common first-session tasks

```
In opencode, just ask naturally — instructions guide the agent:

"what ingested projects are available?"
  → agent calls list_projects()

"what would break if I rename write_code_triple?"
  → agent calls impact("write_code_triple", "codecompass")

"I'm about to edit code_parser.py — what else is affected?"
  → agent calls blast_radius("ingestion/code_parser.py", "codecompass")

"I'm changing these 3 files — full blast radius?"
  → agent calls batch_impact("file1, file2, file3", "codecompass")

"show me the codecompass project structure"
  → agent calls tree("codecompass")
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
    │                     Python, JS, TS, TSX → CALLS, IMPORTS, INHERITS
    │                     CSS, SCSS → DEFINED_IN, USES_VAR, IMPORTS
    │                     HTML → REFERENCES, INCLUDES
    │                     .styles.ts (Lit) → secondary CSS pass on css`...` blocks
    │                                        → USES_VAR + DEFINED_IN for design tokens
    ▼
Neo4j                   — typed relationships: [:CALLS], [:IMPORTS],
                          [:INHERITS], [:STYLES], [:DEFINED_IN], [:USES_VAR], …
    │
    ▼
mcp_server.py           — MCP server exposing 8 tools (blast_radius, impact,
                          deps, trace, tree, styles, batch_impact, list_projects)
    │
    ▼
opencode agent          — calls MCP tools from any directory via instructions
```

Typed relationships (not generic `RELATION {type: ...}`) mean variable-length path queries are index-scannable on Neo4j Community Edition.

---

## Project structure

```
codecompass/
├── graph/
│   ├── code_graph_client.py    Neo4j I/O — nodes, edges, traversal queries
│   ├── code_query_cli.py       CLI — blast-radius / batch-impact / deps /
│   │                                  impact / trace / styles / tree
│   └── mcp_server.py           MCP server — exposes 8 tools to opencode
├── ingestion/
│   ├── code_parser.py          tree-sitter extraction + Lit css`...` pass
│   ├── hierarchy_builder.py    Project → Folder → File skeleton
│   ├── file_watcher.py         incremental updates on file change
│   └── code_normalizer.py      optional Haiku normalization pass
├── memory/
│   ├── decisions.md            architectural decisions (append-only)
│   └── learnings.md            session learnings (auto-saved by plugin)
├── models/
│   └── code_types.py           CodeTriple, FileNode, FolderNode
├── opencode/
│   ├── config.template.json    opencode config template (MCP + plugin + instructions)
│   ├── instructions.md         graph-first query rules loaded into every session
│   ├── plugins/memory.ts       session memory plugin (compaction + idle hooks)
│   └── scripts/                Python helpers called by the plugin
├── config.py                   Neo4j config from .env
├── main.py                     CLI: ingest-code / load-triples / watch
├── install.sh                  one-command setup
└── docker-compose.yml          Neo4j container
```

---

## Automatic AGENTS.md registration

Every `ingest-code` run writes a `## Code graph` block into the target project's `AGENTS.md` (creating the file if it doesn't exist). The block is wrapped in HTML comment markers so re-ingesting safely updates it in place.

This means opencode automatically picks up the right `--project` name and query commands the next time a session opens in that directory — no manual setup.

---

## Troubleshooting

**`connection refused` on Neo4j**
Neo4j is not running. Start your DBMS or use `docker run -d neo4j`.

**`authentication failure` on Neo4j**
Password in `.env` doesn't match. Reset it in Neo4j Desktop or recreate the Docker container.

**`codecompass: command not found`**
Run `pip install codecompass-mcp` to install the CLI.

**MCP tools not appearing**
Run `opencode debug config` to verify the codecompass MCP server is registered. Restart opencode after config changes.

**`memory/learnings.md` is empty**
Learnings are saved when compaction fires during long sessions. The plugin writes entries automatically on compaction and idle events.

---

## Limitations

- Structure only — the graph knows what calls what, not what anything *means*
- Supported languages: Python, JS, TS, TSX, HTML, CSS, SCSS, `.styles.ts` (Lit)
- External callers (consumers outside the ingested repo) won't appear in `impact`
- Lit CSS extraction covers explicit `var(--foo)` usages and `:host { --foo: ... }` declarations; generated property names from `theme.props()` patterns are not yet indexed
- If Neo4j is down, the MCP server returns a clear error instead of a traceback
- The watcher (`codecompass watch`) is separate from the MCP server — keep it running for live re-indexing on file changes
