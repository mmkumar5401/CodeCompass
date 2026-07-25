# Project Memory

High-level architectural context and decisions.

## Graph contents
- Every in-project Entity node carries `line` (definition line, from DEFINED_IN
  triples; modules = 1). External symbols have no `file` and no `line`.
- All entity-level query outputs include the line (`--grep`, `--impact`,
  `--deps`, `--dead-code`, `--flow`, MCP tools). `--blast-radius`/`--tree` are
  file-level and have none.

## Descriptions
- Descriptions are `description` attributes ON the graph nodes. The ingest join
  (`node.setdefault`, fresh parser values win — and the parser never writes
  descriptions) carries them across rebuilds; a deleted/renamed symbol takes
  its description with it. No sidecar: pre-7.0 `description.jsonl` files are
  adopted onto nodes on first client load, then deleted.

## Agent-in-the-loop enrichment
- `add_entity` / `add_call` / `modify_relation` / `delete_entity` /
  `delete_call` (MCP + `ingestion/agent_writes.py`): agents record parser
  misses and correct wrong edges as they read code. Agent-written nodes/edges
  are marked `agent_inferred`; `modify_relation` adds `agent_relation=True`,
  which makes the join drop the parser's conflicting relation for that pair.
  Relations are free-form (only CONTAINS/DEFINED_IN refused); ambiguous names
  return candidates, retrievable by file or id.
- `ingest_code` builds graph.json.copy, joins the old graph's agent data onto
  it, and atomically swaps it in — agent contributions survive re-ingest.

## Vector search
- `graph/vector_store.py` embeds entity name/kind/file/description (read off
  the graph nodes) into `.codecompass/vectors.tvim` — a turbovec
  (Rust/TurboQuant) IdMapIndex; payloads live in a `vectors.meta.json` sidecar
  keyed by uint64 sha1 of node id. Wiped and rebuilt at the end of every
  `ingest_code` (Phase 5, skipped without the `[search]` extra). Query path:
  MCP `search` → `search_entities`. turbovec `search()` returns
  (n_queries, k) 2-D arrays.

## Guard hooks (Claude + pi + opencode)
- Init writes canonical files to `.agents/` first: `codecompass.md` (the
  instruction block — the version signal for auto-heal) and
  `hooks/block-file-search.py` (one guard script for all hosts). Per-host md
  pointers: `.claude/CLAUDE.md`, `.pi/SYSTEM.md`, `.opencode/AGENTS.md` (all
  uppercase), each carrying the exploration checklist. The root AGENTS.md
  managed block is STRIPPED on init (hosts read their own files). Pre-7.0
  locations (root claude.md, .pi/agent/AGENTS.md) are removed when generated;
  existence
  checks across case variants must use listdir, not os.path.exists — macOS
  filesystems are case-insensitive.
- The guard script serves every host: Claude Code blocks on exit 2 + stderr;
  pi (via the pi-hooks extension) and opencode (via opencode-hooks-api) parse
  the deny JSON on stdout. Tool names are lowercased before matching; repo
  matching is case-insensitive (a lowercase $PWD against a proper-case
  registry silently allowed everything).
- Claude wiring: PreToolUse matchers in `.claude/settings.json`, regex
  `^(Bash|bash)$` etc. covering both Claude and opencode tool names, command
  `${CLAUDE_PROJECT_DIR:-.}`-relative so it resolves under both hosts.
- pi wiring: `.pi/settings.json` (pi-hooks format, matcher `^(bash|grep|glob)$`,
  absolute baked command). Requires `npm:@hsingjui/pi-hooks` — `setup-pi`
  installs it alongside pi-mcp-adapter.
- opencode wiring: `_ensure_opencode_config` registers `opencode-hooks-api` in
  the repo's `opencode.json`; `codecompass setup-opencode` / `setup` merges the
  plugin + MCP server into the global `~/.config/opencode/opencode.json`. The
  plugin reads `.claude/settings.json` — no opencode-specific hook file.
- Blocking is scoped by the global registry `~/.codecompass/repos`
  (`CODECOMPASS_REPOS` env overrides): the script allows grep/cat outside
  registered repos. Tests must set CODECOMPASS_REPOS (tests/conftest.py does)
  or the real registry gets polluted.
- `codecompass setup-pi` (`pi_setup.py`) wires pi globally: installs
  pi-mcp-adapter + pi-hooks if missing, copies the skill to
  `~/.pi/agent/skills/`, registers the `codecompass-mcp` server in
  `~/.pi/agent/mcp.json`. Auto-runs (quiet) on the first CLI / MCP-server
  invocation.

## Templates
- The canonical instruction block (`_agents_block`) and the exploration
  checklist (`_EXPLORATION_CHECKLIST`, in every per-host md) live in `main.py`.
  The pi skill text is `_SKILL_MD` in `pi_setup.py`.
