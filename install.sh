#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

echo "=== CodeCompass setup for opencode ==="
echo "Tip: pip install codecompass-mcp is the fastest way."

# 1. Python deps
echo ""
echo "→ Installing Python dependencies..."
pip install -e .[dev] -q
echo "  Dependencies installed (including MCP SDK)."

# 2. .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ Created .env from .env.example"
  echo "  Edit .env and set your ANTHROPIC_API_KEY and NEO4J_PASSWORD before continuing."
  echo ""
  read -rp "  Press Enter once .env is configured, or Ctrl-C to exit..."
else
  echo "→ .env already exists, skipping"
fi

# 3. Neo4j check
echo ""
echo "→ Checking Neo4j connection..."
python -c "
import sys, os
os.chdir('$REPO_ROOT')
from dotenv import load_dotenv
load_dotenv(dotenv_path='$REPO_ROOT/.env', override=True)
from config import neo4j_config
from neo4j import GraphDatabase
cfg = neo4j_config()
try:
    driver = GraphDatabase.driver(cfg['uri'], auth=(cfg['user'], cfg['password']))
    driver.verify_connectivity()
    driver.close()
    print('  Neo4j is reachable.')
except Exception as e:
    print(f'  ERROR: cannot connect to Neo4j — {e}')
    print('  Start Neo4j and re-run install.sh')
    sys.exit(1)
"

# 4. Ingest the codebase into the code graph
echo ""
echo "→ Ingesting codebase into code graph (project: codecompass)..."
python -m main ingest-code . --project codecompass
echo "  Code graph ready."

# 5. Set up memory files
echo ""
echo "→ Setting up memory files..."
mkdir -p memory
touch memory/learnings.md
touch memory/session_log.md
echo "  memory/ ready."

# 6. Generate opencode config via setup
echo ""
echo "→ Running codecompass setup..."
python -m graph.setup
echo ""

echo "=== Done ==="
echo ""
echo "Restart opencode for CodeCompass to take effect."
echo "Try: opencode"
