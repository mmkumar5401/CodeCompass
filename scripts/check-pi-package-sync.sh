#!/usr/bin/env bash
# Check that the pi-package templates stay in sync with the repo's
# .pi/APPEND_SYSTEM.md and AGENTS.md.
set -e
cd "$(dirname "$0")/.."
diff -q .pi/APPEND_SYSTEM.md pi-package/templates/APPEND_SYSTEM.md && \
diff -q AGENTS.md pi-package/templates/AGENTS.md && \
echo "OK: templates in sync"
