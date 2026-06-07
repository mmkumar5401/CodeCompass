#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

echo "=== GraphRAG setup ==="

# 1. Python deps
echo ""
echo "→ Installing Python dependencies..."
pip install -r requirements.txt -q

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
python - <<'EOF'
import sys
from dotenv import load_dotenv
load_dotenv(override=True)
from config import neo4j_config
from neo4j import GraphDatabase
cfg = neo4j_config()
try:
    driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
    driver.verify_connectivity()
    driver.close()
    print("  Neo4j is reachable.")
except Exception as e:
    print(f"  ERROR: cannot connect to Neo4j — {e}")
    print("  Start Neo4j and re-run install.sh")
    sys.exit(1)
EOF

# 4. Ingest the codebase into the code graph
echo ""
echo "→ Ingesting codebase into code graph (project: graphrag)..."
python main.py ingest-code . --project graphrag --skip-normalize
echo "  Code graph ready."

echo ""
echo "=== Done ==="
echo ""
echo "Start a Claude Code session from this directory:"
echo "  claude"
echo ""
echo "Memory auto-loads at session start. Graph grows as you use it."
