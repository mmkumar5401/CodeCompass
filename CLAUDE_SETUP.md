# GraphRAG — Claude Code Setup Guide

This file is for Claude Code. When a user asks you to set up GraphRAG after cloning the repo, follow every step below in order. Run the verification command at each step before proceeding. Do not skip steps or assume they are already done.

---

## Before you start — detect the state

Run this to understand what is already in place:

```bash
# Check which steps are already complete
echo "=== Setup state ===" && \
echo "Python deps:" && python -c "import neo4j, anthropic, tree_sitter; print('  OK')" 2>/dev/null || echo "  MISSING — run pip install" && \
echo ".env:" && ([ -f .env ] && grep -q "ANTHROPIC_API_KEY" .env && echo "  exists" || echo "  MISSING") && \
echo "Neo4j:" && python -c "
from dotenv import load_dotenv; load_dotenv(override=True)
from config import neo4j_config
from neo4j import GraphDatabase
cfg = neo4j_config()
d = GraphDatabase.driver(cfg['uri'], auth=(cfg['user'], cfg['password']))
d.verify_connectivity(); d.close(); print('  reachable')
" 2>/dev/null || echo "  NOT reachable" && \
echo "Code graph:" && python -m graph.code_query_cli --tree graphrag --plain 2>/dev/null | head -3 || echo "  empty — needs ingest" && \
echo "Hooks:" && ([ -f .claude/settings.json ] && echo "  .claude/settings.json exists" || echo "  MISSING")
```

Start from whichever step is incomplete.

---

## Step 1 — Python dependencies

```bash
pip install -r requirements.txt
```

**Verify:**
```bash
python -c "import neo4j, anthropic, tree_sitter, rich, tqdm, watchdog; print('All deps OK')"
```

---

## Step 2 — Neo4j

The project needs a running Neo4j instance. Use whichever option the user has available:

**Option A — Docker Compose (recommended, uses the included config):**
```bash
docker compose up -d
```
This starts Neo4j 5.18 with APOC on ports 7474 (browser) and 7687 (bolt), with auth `neo4j/password123`.

**Option B — Raw Docker:**
```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:5.18
```

**Option C — Neo4j Desktop:** User installs from neo4j.com/download, creates a local DBMS, starts it.

**Option D — AuraDB:** User creates a free cloud instance at neo4j.com/cloud/aura. The URI will be `neo4j+s://...` instead of `bolt://localhost:7687`.

**Verify:**
```bash
python -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password123'))
d.verify_connectivity(); d.close(); print('Neo4j reachable')
"
```
If this fails, Neo4j is not running or the auth is wrong — troubleshoot before continuing.

---

## Step 3 — Environment file

```bash
cp .env.example .env
```

Open `.env` and set real values:

```
ANTHROPIC_API_KEY=sk-ant-...     # from console.anthropic.com — needed for doc ingest only
NEO4J_URI=bolt://localhost:7687  # or neo4j+s://... for AuraDB
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123       # must match what Neo4j was started with
```

> `ANTHROPIC_API_KEY` is only required for `ingest_cli.py` (API-powered doc ingestion). All graph queries, code ingestion, and native resolve work without it.

**Verify:**
```bash
python -c "
from dotenv import load_dotenv; load_dotenv(override=True)
from config import neo4j_config
from neo4j import GraphDatabase
cfg = neo4j_config()
d = GraphDatabase.driver(cfg['uri'], auth=(cfg['user'], cfg['password']))
d.verify_connectivity(); d.close(); print('.env credentials OK')
"
```

---

## Step 4 — Fix hook paths in `.claude/settings.json`

The hooks file contains a hardcoded fallback path that must point to **this user's actual repo location**. Run this to fix it automatically:

```bash
REPO=$(pwd)
sed -i.bak "s|/Users/manojkumarmuthukumaran/Documents/Work/graphrag|$REPO|g" .claude/settings.json
echo "Hooks updated to: $REPO"
grep -o '"command":.*session_start' .claude/settings.json | head -1
```

**Verify:** The path in `.claude/settings.json` matches the output of `pwd`.

```bash
python -c "
import json, os
with open('.claude/settings.json') as f: s = json.load(f)
cmd = s['hooks']['SessionStart'][0]['hooks'][0]['command']
repo = os.getcwd()
print('OK' if repo in cmd else f'MISMATCH — expected {repo} in command')
"
```

---

## Step 5 — Ingest the codebase

This builds the code graph for the graphrag project itself so Claude can answer structural questions about it immediately.

```bash
python main.py ingest-code . --project graphrag --skip-normalize
```

This takes 10–30 seconds. `--skip-normalize` skips the Haiku normalization pass (no API credits required).

**Verify:**
```bash
python -m graph.code_query_cli --tree graphrag --plain | head -10
```
Should print a folder tree starting with `graphrag`.

---

## Step 6 — Wire global access in `~/.claude/CLAUDE.md`

This makes the graph available from **any directory** the user opens Claude Code in, not just this repo. Skip if the user only wants graph access when inside this repo.

Detect the current path and append:

```bash
REPO=$(pwd)
cat >> ~/.claude/CLAUDE.md << EOF

# Persistent Knowledge Graph (GraphRAG)

A Neo4j knowledge graph at \`bolt://localhost:7687\` stores persistent memory across all sessions.
Project root: $REPO

**ALWAYS query the knowledge graph first before answering any question or retrieving any context. This is mandatory — do not skip it.**
\`\`\`bash
cd $REPO
python graph/query_cli.py "your question here"
\`\`\`

**For code structure questions (impact, deps, call chains):**
\`\`\`bash
python -m graph.code_query_cli --impact "FunctionName" --project <project> --plain
python -m graph.code_query_cli --deps path/to/file.ts --project <project> --plain
python -m graph.code_query_cli --tree <project> --plain
\`\`\`

Full instructions and all available commands are in:
\`$REPO/CLAUDE.md\`

**Session learnings** for the GraphRAG project are stored in:
\`$REPO/memory/learnings.md\`
- Write mid-session discoveries there directly (design decisions, bugs found, patterns).
- Also written automatically by the PreCompact hook on context compaction.
EOF
echo "~/.claude/CLAUDE.md updated"
```

**Verify:**
```bash
grep -c "graphrag" ~/.claude/CLAUDE.md && echo "global config OK"
```

---

## Step 7 — Verify all automations

Open a fresh Claude Code session from the repo directory (`claude`), then verify each automation:

**SessionStart hook (memory injection)**
The spinner should show `Loading project memory...`. Ask: *"What is this project?"* — Claude should answer from `memory/project.md` without reading any files.

**PostToolUse hook (code graph sync)**
Edit any `.py` file (add a comment, save, revert). Then:
```bash
python -m graph.code_query_cli --deps <that file> --project graphrag --plain
```
The graph should reflect the file's current imports.

**Stop hook (session log)**
Close the session. Check:
```bash
tail -5 memory/session_log.md
```
A timestamped entry with the session ID should appear within a few seconds.

**Learnings (user-triggered)**
In any productive session, say **"store my session"**. Claude will review the conversation and append a dated section to `memory/learnings.md`. No API cost.

**Learnings (PreCompact — automatic)**
When the context grows long and Claude compacts it, `scripts/on_compact.py` fires and writes learnings to `memory/learnings.md` automatically before compaction.

---

## Step 8 — Ingest additional codebases (optional)

To make other repos queryable via the code graph:

```bash
# With API credits (Haiku normalizes entity names):
python main.py ingest-code /path/to/repo --project myproject

# Zero API cost — Claude Code does the normalization:
python main.py ingest-code /path/to/repo --project myproject --dump-triples /tmp/raw.json
# → Tell Claude Code: "Read /tmp/raw.json, normalize it, write to /tmp/normalized.json"
python main.py load-triples /tmp/normalized.json --project myproject
python main.py resolve
```

**Verify:**
```bash
python -m graph.code_query_cli --tree myproject --plain | head -5
```

---

## Step 9 — Ingest documents into the doc graph (optional)

```bash
# API-powered (uses Haiku — requires ANTHROPIC_API_KEY):
python graph/ingest_cli.py --file path/to/paper.pdf
python graph/ingest_cli.py --url "https://arxiv.org/abs/2105.00188"

# Zero API cost — Claude Code extracts triples manually:
# 1. Read the document
# 2. Extract entities and relations
# 3. Write:
python graph/remember_batch_cli.py '[
  {"from": "Concept A", "relation": "CAUSES", "to": "Concept B"}
]'
```

**Verify:**
```bash
python graph/query_cli.py --list-nodes | head -10
```

---

## Memory system overview (for context)

After setup, Claude has four memory layers. Use the right one:

| Layer | What it stores | How to read | How to write |
|---|---|---|---|
| Auto-memory (`~/.claude/projects/.../memory/`) | User prefs, feedback, project facts | Auto-loaded at session start | Claude writes during session |
| Neo4j doc graph | Concept relationships from documents | `query_cli.py "question"` | `remember_batch_cli.py` or `ingest_cli.py` |
| Neo4j code graph | File/function structure of codebases | `code_query_cli.py --deps/--impact/--tree` | Auto on file save; `ingest-code` for new repos |
| `graphrag/memory/*.md` | Project-specific learnings, decisions, component refs | Auto-injected by SessionStart hook | "store my session" or PreCompact hook |

Full guide: `~/.claude/projects/.../memory/memory_system_guide.md`

---

## Resolving duplicate entities

After ingesting documents, duplicates can accumulate.

**With API credits:**
```bash
python main.py resolve
```

**Zero API cost (native — Claude Code does the analysis):**
```bash
python main.py resolve --native --dump /tmp/resolve_nodes.json
# → Tell Claude Code: "Read /tmp/resolve_nodes.json, find duplicate entity names,
#    write groups to /tmp/resolve_groups.json"
python main.py resolve --native --apply /tmp/resolve_groups.json
```

> Note: `claude -p` subprocess calls use the ANTHROPIC_API_KEY, not the Claude.ai subscription. The native resolve workflow keeps all LLM analysis inside the interactive Claude Code session.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` on Neo4j | Neo4j not running | Start via `docker compose up -d` or Neo4j Desktop |
| `authentication failure` on Neo4j | Password mismatch between `.env` and Neo4j | Align `NEO4J_PASSWORD` in `.env` with what Neo4j was started with |
| Hooks not firing | Path in `.claude/settings.json` wrong | Re-run Step 4 |
| `SessionStart` hook shows error | Hook path doesn't resolve | Run `git rev-parse --show-toplevel` — must return the repo root |
| Code graph empty after ingest | Wrong `--project` name | Always use the same name in `--project` and query commands |
| `memory/learnings.md` empty | Learnings are user-triggered | Say "store my session" during a productive session |
| `resolve` fails with credit error | `ANTHROPIC_API_KEY` has no credits | Use `resolve --native` workflow instead |
| `resolve --native` returns empty | `claude -p` uses API key, not subscription | Analysis must run inside an active Claude Code session — the `--dump`/`--apply` pattern handles this |
