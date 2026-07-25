#!/usr/bin/env bash
# CodeCompass installer — safe to pipe from curl:
#   curl -fsSL https://raw.githubusercontent.com/mmkumar5401/CodeCompass/main/install.sh | bash
#
# What it does:
#   1. installs the codecompass-mcp package with `uv tool install` — uv brings
#      its own managed Python, so this works with no system Python and never
#      touches a project venv. If uv is missing it is installed first.
#   2. runs `codecompass setup`, which wires every agent host present, pointing
#      them all at the uv binary (~/.local/bin/codecompass-mcp):
#      - pi:       pi-mcp-adapter + pi-hooks extensions, skill, MCP server entry
#      - opencode: opencode-hooks-api plugin + MCP server in the global config
#      Per-project files (AGENTS.md, .agents/, guard hooks) are written by
#      `init`, which runs automatically the first time the MCP server is used
#      in a repo.
set -euo pipefail

PKG="codecompass-mcp"
UV_BIN="$HOME/.local/bin"

say()  { printf '→ %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. uv -------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  say "uv not found — installing it (brings its own Python)..."
  command -v curl >/dev/null 2>&1 || fail "curl not found. Install uv manually: https://docs.astral.sh/uv/"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$UV_BIN:$PATH"
fi
command -v uv >/dev/null 2>&1 || fail "uv installation failed."

# --- 2. Install the package ---------------------------------------------------
say "Installing $PKG with uv (isolated, no venvs touched)..."
uv tool install --force --refresh "$PKG"

CODECOMPASS="$UV_BIN/codecompass"
[ -x "$CODECOMPASS" ] || fail "$PKG installed but $CODECOMPASS is missing."

# --- 3. Wire agent hosts ------------------------------------------------------
say "Wiring agent hosts (pi, opencode — whichever is installed)..."
"$CODECOMPASS" setup

echo
echo "=== CodeCompass installed ==="
echo "MCP server: $UV_BIN/codecompass-mcp (registered with pi and/or opencode above)"
echo "Claude Code users: claude mcp add codecompass -- $UV_BIN/codecompass-mcp"
echo "Make sure $UV_BIN is on your PATH."
echo "Per-project setup (AGENTS.md, guard hooks) happens automatically on first use."
