# Project Memory

High-level architectural context and decisions.

## Graph contents
- Every in-project Entity node carries `line` (definition line, from DEFINED_IN
  triples; modules = 1). External symbols have no `file` and no `line`.
- All entity-level query outputs include the line (`--grep`, `--impact`,
  `--deps`, `--dead-code`, `--flow`, MCP tools). `--blast-radius`/`--tree` are
  file-level and have none.

## Agent-in-the-loop enrichment
- `enrich` (the only swarm pass; `describe` was removed as redundant) stages
  entities with signature/snippet + known callers/callees; sub-agents return
  one-line descriptions and missing calls; `--apply` merges. Ambiguous call
  targets are skipped, never guessed.
- `add_entity` / `add_call` (CLI + MCP) are the opportunistic version: agents
  record parser misses as they read code. All agent-written nodes/edges/
  descriptions are marked `agent_inferred=True`.
- `ingest_code` does `graph.clear()` + full rebuild, but snapshots
  `agent_inferred` data first and restores it after — agent contributions
  survive re-ingest.

## Guard hooks (Claude + pi)
- Blocking is scoped by a global registry `~/.codecompass/repos` (one abs path
  per `init`'d repo; `CODECOMPASS_REPOS` env overrides). Hooks block
  grep/rg/cat and Grep/Glob tools only when the target path (or cwd, for
  unparseable commands) is inside a registered repo; everything else passes.
- The Claude hook is generated per-project into `.claude/hooks/` with the
  project root baked in (`_REPO`); settings.json invokes it via
  `$CLAUDE_PROJECT_DIR` so it works from subdirectories. `init` rewrites only
  hook copies it installed.
- The pi guard (`.pi/extensions` + `pi-package/extensions`) implements the
  same registry logic in TS and additionally injects `APPEND_SYSTEM.md` into
  the system prompt every turn.

## Templates & sync
- The AGENTS.md managed block lives in `main.py`; root `AGENTS.md` regenerates
  on init/ingest; `pi-package/templates/AGENTS.md` regenerates via
  `scripts/sync_pi_package_templates.py`; `scripts/check-pi-package-sync.sh`
  diffs templates against `.pi/APPEND_SYSTEM.md`.
