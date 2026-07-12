#!/usr/bin/env bash
# Check that the pi-package templates stay in sync with the repo's
# .pi/APPEND_SYSTEM.md and the canonical AGENTS.md block in main.py.
set -e
cd "$(dirname "$0")/.."

tmp_agents=$(mktemp)
trap 'rm -f "$tmp_agents"' EXIT
python3 scripts/sync_pi_package_templates.py --output "$tmp_agents"
diff -q .pi/APPEND_SYSTEM.md pi-package/templates/APPEND_SYSTEM.md && \
diff -q "$tmp_agents" pi-package/templates/AGENTS.md && \
echo "OK: templates in sync"
