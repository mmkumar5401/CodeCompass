# Onboarding Guide

This document walks through setting up GraphRAG from scratch. It is written for both humans and Claude Code — if you are Claude Code helping a user set up this project, follow each step in order and verify it passes before moving to the next.

---

## Step 1 — Clone the repository

```bash
git clone <repo-url>
cd graphrag
```

**Verify:** you are inside the `graphrag` directory and can see `install.sh`, `CLAUDE.md`, and `main.py`.

---

## Step 2 — Start Neo4j

GraphRAG needs a running Neo4j instance before setup can complete. Pick one:

**Docker (fastest, nothing to install)**
```bash
docker run --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password neo4j:latest
```

**Neo4j Desktop**
1. Download from [neo4j.com/download](https://neo4j.com/download)
2. Create a new project → Add → Local DBMS
3. Set a password → click Start

**AuraDB (cloud)**
1. Sign up at [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura)
2. Create a free instance — copy the URI, username, and password

**Verify:** Neo4j is reachable at `bolt://localhost:7687` (or your cloud URI). The Neo4j Browser at `http://localhost:7474` should load if using local.

---

## Step 3 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```
ANTHROPIC_API_KEY=your_key_here
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com) → API Keys. Required for document ingestion. Not needed for read-only graph queries.
- `NEO4J_URI` — use the bolt URI from your Neo4j instance. AuraDB URIs start with `neo4j+s://`.
- `NEO4J_PASSWORD` — must match what you set when starting Neo4j.

**Verify:** `.env` exists and has real values, not placeholders.

---

## Step 4 — Run the installer

```bash
./install.sh
```

This does four things in order:
1. Installs Python dependencies from `requirements.txt`
2. Checks that Neo4j is reachable with your `.env` credentials
3. Ingests the graphrag codebase itself into the code graph (so Claude immediately knows the project structure)
4. Prints confirmation

**If Neo4j check fails:** make sure Neo4j is started and the password in `.env` matches what you set in Step 2.

**Verify:** the script completes without errors and prints `=== Done ===`.

---

## Step 5 — Register globally with Claude Code (recommended)

This step makes the knowledge graph available from **any directory** you work in — not just the graphrag project folder. Skip it if you only want graph access when working inside this repository.

```bash
cat >> ~/.claude/CLAUDE.md << 'EOF'

# Persistent Knowledge Graph (GraphRAG)

A Neo4j knowledge graph at `bolt://localhost:7687` stores persistent memory across all sessions.
Project root: /path/to/graphrag    ← replace with your actual path

ALWAYS query the knowledge graph first before answering any question or retrieving any context. This is mandatory.

```bash
cd /path/to/graphrag
python graph/query_cli.py "your question here"
```

For code structure questions:
```bash
python -m graph.code_query_cli --deps path/to/file.py --project <project> --plain
python -m graph.code_query_cli --impact "FunctionName" --project <project> --plain
python -m graph.code_query_cli --tree <project> --plain
```

Full instructions: /path/to/graphrag/CLAUDE.md
EOF
```

Replace `/path/to/graphrag` with the actual path (e.g. `/Users/you/Documents/Work/graphrag`).

**Verify:** `cat ~/.claude/CLAUDE.md` shows the block you just added.

---

## Step 6 — Open Claude Code

```bash
claude
```

When the session starts, you will see `Loading project memory...` in the spinner. That is the `SessionStart` hook reading the `memory/` directory and injecting it. Claude now knows the project structure, design decisions, and everything accumulated in previous sessions.

**Verify:** Ask Claude `"what is this project?"` — it should answer from memory without needing to read any files.

---

## Step 7 — Add your first knowledge

The graph starts empty except for the code structure ingested in Step 4. Add knowledge in any of these ways:

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
python main.py ingest-code /path/to/other-repo --project myproject --skip-normalize
```

**Verify:** `python graph/query_cli.py --list-nodes` shows the entities you just added.

---

## Step 8 — Verify all three automations work

**File memory (SessionStart)**
Close and reopen Claude Code. The memory spinner should appear. Ask something that's in `memory/project.md` — Claude should know it without reading the file.

**Code graph sync (PostToolUse)**
Edit any `.py` file in the project. The hook runs silently in the background and re-ingests that file. Run `python -m graph.code_query_cli --deps <that file> --project graphrag --plain` — it should reflect your edit.

**Session learnings (Stop)**
End a session where you discussed something non-trivial. Check `memory/learnings.md` — a dated entry should have been appended. (This uses `claude -p` internally so it takes a few seconds after the session closes.)

---

## What happens every session

```
Open Claude Code
    ↓
SessionStart hook fires → memory/ injected as context
    ↓
You ask questions / make edits
    ↓
Each file save → on_file_change.py → code graph updated
    ↓
Close session
    ↓
Stop hook fires → auto_memory.py → new learnings written to memory/learnings.md
```

---

## Common first-session tasks

**"What files should I read to understand the query pipeline?"**
```bash
python -m graph.code_query_cli --trace "run_agentic_agent" --project graphrag --plain
```

**"What concepts are in the graph?"**
```bash
python graph/query_cli.py --list-nodes
```

**"I just finished reading a paper. Add it to memory."**
```bash
python graph/ingest_cli.py --file path/to/paper.pdf
# or, zero cost:
# Read the paper yourself, extract key facts, then:
python graph/remember_batch_cli.py '[{"from": "...", "relation": "...", "to": "..."}]'
```

**"Show me the structure of this project."**
```bash
python -m graph.code_query_cli --tree graphrag --plain
```

---

## Troubleshooting

**`connection refused` on Neo4j**
Neo4j is not running. Start your DBMS in Neo4j Desktop, or run the Docker command from Step 2.

**`authentication failure` on Neo4j**
Password in `.env` does not match what Neo4j was started with. Reset the password in Neo4j Desktop or recreate the Docker container with the correct `NEO4J_AUTH` value.

**`ANTHROPIC_API_KEY` error during ingest**
The key in `.env` is missing or invalid. Ingest via `ingest_cli.py` requires a valid key. Read-only queries (`query_cli.py`, `code_query_cli.py`) and manual writes (`remember_batch_cli.py`) do not.

**SessionStart hook not firing**
Open `/hooks` in the Claude Code UI to reload the hook configuration, or restart the session. Hooks only load when the session starts in a directory that had a `.claude/settings.json` when Claude Code launched.

**`memory/learnings.md` not being written after sessions**
The Stop hook uses the `claude` binary. If your machine installed Claude Code via nvm, the binary path may differ from what `auto_memory.py` expects. Check the `_find_claude()` function in `scripts/auto_memory.py` and add your path to the candidates list.

**Code graph is stale after editing files**
The `on_file_change.py` hook only handles Python files (and other supported extensions). Check `ingestion/code_parser.py` → `SUPPORTED_EXTENSIONS` to see what's covered.
