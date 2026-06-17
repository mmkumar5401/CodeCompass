# CodeCompass — Code Intelligence Engine for AI Coding Agents

Full-indexes an average repository in seconds, a large monorepo in minutes. Answers structural queries in under 3 seconds — *"what should I read before editing X?"*

Neo4j-backed code dependency graph. Ingest once, then opencode's MCP tools (`blast_radius`, `impact`, `deps`, `trace`, `tree`, `styles`, `batch_impact`) tell the agent exactly which files to read — no blind exploration.

---

## What's new in v2.0

| Feature | Description |
|---|---|
| MCP server | Code graph exposed as native opencode tools — `blast_radius`, `impact`, `deps`, `trace`, `tree`, `styles`, `batch_impact`, `list_projects` |
| opencode plugin | Session memory auto-saves on compaction + idle — replaces old Claude Code hooks |
| One-command setup | `./install.sh` installs deps, ingests code, writes opencode config with MCP + instructions + plugin |
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
- Docker (for Neo4j)
- opencode CLI

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

This writes a `## Code graph` section into the project's `AGENTS.md` automatically, so opencode picks up the graph context on the next session.

### Set up session memory (optional)

```bash
cp memory/learnings.example.md memory/learnings.md
```

`memory/learnings.md` is gitignored — your notes stay local. opencode's session plugin auto-saves learnings on compaction and idle.

---

## Detailed setup walkthrough

### Step 1 — Clone the repository

```bash
git clone <repo-url>
cd codecompass
```

**Verify:** you are inside the `codecompass` directory and can see `install.sh`, `main.py`, and `POSITIONING.md`.

### Step 2 — Start Neo4j

Pick one:

**Docker (fastest)**
```bash
docker run --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password neo4j:latest
```

**Neo4j Desktop** — Download from [neo4j.com/download](https://neo4j.com/download), create project → Add → Local DBMS, set password, click Start.

**AuraDB (cloud)** — Sign up at [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura), create a free instance, copy the URI/username/password.

**Verify:** Neo4j is reachable at `bolt://localhost:7687`. The Neo4j Browser at `http://localhost:7474` should load (if local).

### Step 3 — Configure environment

```bash
cp .env.example .env
```

Fill in:
```
ANTHROPIC_API_KEY=your_key_here          # from console.anthropic.com (needed for doc ingestion only)
NEO4J_URI=bolt://localhost:7687           # use neo4j+s:// for AuraDB
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

**Verify:** `.env` has real values, not placeholders.

### Step 4 — Run the installer

```bash
./install.sh
```

This installs Python dependencies, checks Neo4j connectivity, ingests the codecompass codebase into the code graph, and prints confirmation.

**Verify:** script completes without errors and prints `=== Done ===`.

### Step 5 — Register globally with opencode (recommended)

Makes the graph available from any directory via MCP tools + instructions. The installer writes this config to `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["/path/to/codecompass/opencode/instructions.md"],
  "mcp": {
    "codecompass": {
      "type": "local",
      "command": ["python", "-m", "graph.mcp_server"],
      "cwd": "/path/to/codecompass"
    }
  },
  "plugin": ["/path/to/codecompass/opencode/plugins/memory.ts"]
}
```

Replace `/path/to/codecompass` with the actual path.

**Verify:** `opencode debug config` shows the codecompass MCP server and instructions loaded.

### Step 6 — Open opencode

```bash
opencode
```

The codecompass MCP tools (`blast_radius`, `impact`, `deps`, etc.) are available from any working directory. Instructions tell the agent to query the graph before editing.

**Verify:** Ask opencode "what ingested projects are available?" — it should use `list_projects` to answer.

### Step 7 — Add your first knowledge

**Ingest a document (uses Haiku, requires API key)**
```bash
python graph/ingest_cli.py --file path/to/paper.pdf
python graph/ingest_cli.py --url "https://arxiv.org/abs/2105.00188"
```

**Write facts directly (free, no API cost)**
```bash
python graph/remember_batch_cli.py '[
  {"from": "Concept A", "relation": "CAUSES", "to": "Concept B"},
  {"from": "System X", "relation": "IMPLEMENTS", "to": "Algorithm Y"}
]'
```

**Ingest another codebase**
```bash
python main.py ingest-code /path/to/other-repo --project myproject
```

**Verify:** `python graph/query_cli.py --list-nodes` shows the entities you just added.

### Step 8 — Verify automations work

- **MCP tools:** ask opencode to use `list_projects` or `blast_radius` — tools respond from any directory.
- **Instructions:** the agent queries the graph before editing files in ingested projects.
- **Session memory:** compaction auto-saves learnings to `memory/learnings.md`. Check the file after a long session.
- **Session log:** `memory/session_log.md` gets timestamped entries on session idle events.

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

For direct CLI access (bypassing the agent):
```bash
python -m graph.code_query_cli --trace "run_agentic_agent" --project codecompass
python graph/query_cli.py --list-nodes
python graph/ingest_cli.py --file path/to/paper.pdf
```

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

Watches for file creates, modifies, deletes, and renames. Incrementally re-ingests only changed files. Writes a PID file to `/tmp/codecompass_watcher_<project>.pid` — the query CLI warns if the watcher isn't running.

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
Neo4j is not running. Start your DBMS or run the Docker command from Step 2.

**`authentication failure` on Neo4j**
Password in `.env` doesn't match. Reset it in Neo4j Desktop or recreate the Docker container.

**`ANTHROPIC_API_KEY` error during ingest**
The key is missing/invalid. Read-only queries and manual writes don't need it — only document ingestion does.

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
- The watcher (`python main.py watch`) is separate from the MCP server — keep it running for live re-indexing on file changes
