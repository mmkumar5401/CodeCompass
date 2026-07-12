#!/usr/bin/env bash
# Check that the pi-package templates stay in sync with the repo's
# .pi/APPEND_SYSTEM.md and AGENTS.md.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

check_sync() {
  local src="$1"
  local dst="$2"
  local name="$3"

  if [ ! -f "$src" ]; then
    echo "Missing source: $src"
    return 1
  fi

  if [ ! -f "$dst" ]; then
    echo "Missing template: $dst"
    return 1
  fi

  if ! diff -q "$src" "$dst" >/dev/null 2>&1; then
    echo "OUT OF SYNC: $name"
    echo "  source: $src"
    echo "  template: $dst"
    echo "Run: cp $src $dst"
    return 1
  fi

  echo "OK: $name"
}

check_sync ".pi/APPEND_SYSTEM.md" "pi-package/templates/APPEND_SYSTEM.md" "APPEND_SYSTEM.md"
check_sync "AGENTS.md" "pi-package/templates/AGENTS.md" "AGENTS.md"
