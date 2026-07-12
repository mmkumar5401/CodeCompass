#!/usr/bin/env bash
# Check that the pi-package templates stay in sync with the repo's
# .pi/APPEND_SYSTEM.md and AGENTS.md.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

diff -q .pi/APPEND_SYSTEM.md pi-package/templates/APPEND_SYSTEM.md
diff -q AGENTS.md pi-package/templates/AGENTS.md

echo "OK: templates in sync"
