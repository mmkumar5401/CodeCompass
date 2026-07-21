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
- The pi guard is a lean TS extension (`_PI_GUARD_EXT` in `main.py`) written by
  `_ensure_pi_extension` into `<repo>/.pi/extensions/` on init when pi is
  installed. Project-local placement scopes it — no registry; it blocks
  grep/rg/cat unconditionally in that repo.
- `codecompass setup-pi` (`pi_setup.py`) wires pi globally: installs
  `pi-mcp-adapter` if missing, copies the skill to `~/.pi/agent/skills/`, and
  registers the `codecompass-mcp` server in `~/.config/mcp/mcp.json`. Auto-runs
  (quiet) on the first CLI / MCP-server invocation. The former npm `pi-package`
  is gone — the pip package bootstraps pi entirely.

## Vector search (optional)
- `graph/vector_store.py` embeds entity name/kind/file/description into
  `.codecompass/vectors.lance` (LanceDB + fastembed BGE-small, CPU/ONNX).
- Lifecycle mirrors the graph: wiped and rebuilt wholesale at the end of every
  `ingest_code` (Phase 5), so agent-inferred nodes restored during ingest are
  included. Deps are the `search` extra; Phase 5 is skipped (with a printed
  reason) when they're missing. Query path: MCP `search` → `search_entities`.

## Templates
- The AGENTS.md managed block lives in `main.py`; root `AGENTS.md` regenerates
  on init/ingest. The pi skill text is `_SKILL_MD` in `pi_setup.py`.
