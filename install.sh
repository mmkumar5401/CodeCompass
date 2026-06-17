#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

echo "=== CodeCompass setup for opencode ==="

# 1. Python deps
echo ""
echo "→ Installing Python dependencies..."
pip install -r requirements.txt -q
pip install mcp -q
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
python main.py ingest-code . --project codecompass --skip-normalize
echo "  Code graph ready."

# 5. Set up memory files
echo ""
echo "→ Setting up memory files..."
mkdir -p memory
touch memory/learnings.md
touch memory/session_log.md
echo "  memory/ ready."

# 6. Generate opencode config
OPCODE_CONFIG_DIR="${HOME}/.config/opencode"
OPCODE_CONFIG_FILE="${OPCODE_CONFIG_DIR}/opencode.json"

echo ""
echo "→ Generating opencode config..."
mkdir -p "$OPCODE_CONFIG_DIR"

if [ -f "$OPCODE_CONFIG_FILE" ]; then
  echo "  Existing opencode config found. Creating backup..."
  cp "$OPCODE_CONFIG_FILE" "${OPCODE_CONFIG_FILE}.backup.$(date +%s)"
fi

# Generate config from template with real paths
sed "s|GRAPHRAG_ROOT|${REPO_ROOT}|g" opencode/config.template.json > "${OPCODE_CONFIG_DIR}/opencode.codecompass.json"

echo "  Wrote config to ${OPCODE_CONFIG_DIR}/opencode.codecompass.json"
echo ""
echo "  To activate, merge this into your opencode config:"
echo ""
echo "    cp ${OPCODE_CONFIG_DIR}/opencode.codecompass.json ${OPCODE_CONFIG_FILE}"
echo ""
echo "  Or manually add the codecompass MCP + instructions + plugin sections."
echo "  MCP server: codecompass"
echo "  Instructions: ${REPO_ROOT}/opencode/instructions.md"
echo "  Plugin: ${REPO_ROOT}/opencode/plugins/memory.ts"

# 7. Update the plugin with the real path
sed -i '' "s|REPLACE_WITH_CODECOMPASS_ROOT|${REPO_ROOT}|g" opencode/plugins/memory.ts
echo "  Plugin paths updated."

echo ""
echo "=== Done ==="
echo ""
echo "Restart opencode for the memory layer to take effect."
echo ""
echo "The following are now active from any directory:"
echo "  • MCP tools: blast_radius, impact, deps, trace, tree, styles, batch_impact, list_projects"
echo "  • Instructions: always query the graph before editing code"
echo "  • Session memory: auto-saves learnings on compaction + idle"
echo ""
echo "Try: opencode"
