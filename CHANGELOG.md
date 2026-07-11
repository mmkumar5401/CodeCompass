# Changelog

## [2.7.0] - 2026-07-11

### Added
- **`map` query** — a compact `{file: [symbols]}` index of the codebase
  (~37x leaner than `--tree`) for an agent to reason over during discovery.
  The semantic-discovery entry point for a vague task: read the map, use your
  own judgment to find where a feature belongs, then drill in with
  `flow`/`impact`/`deps`. On an Express ingest this cut the cost of orienting
  to a vague feature ("add response caching") from ~14k tokens (tree + old
  flows) to ~874.
- **`search` query** — keyword lookup over entity names/files/descriptions,
  OR-ranked, returning a lean candidate list. Use when you have a literal
  string/symbol to look for; prefer `map` when intent is semantic.

### Changed
- **`flow` is now lean by default** — returns only the call structure an agent
  needs (node name/kind/file/depth, edge from/to/type/order/line), no embedded
  source or rendered image. This roughly 5x'd the cost on wide flows before.
  The human-facing walkthrough (mermaid flowchart + prose narration, or
  source-embedded json) moved to a new **`flow_summary`** query.
- **Navigation guardrail retargeted and relaxed.** The `init`-installed
  PreToolUse hook (and pi extension) now block only code *search* (`grep`/`rg`,
  the Grep/Glob tools) and whole-file `cat` dumps — routing discovery through
  `--map`/`--search` — while leaving targeted reads (Read tool, `sed -n`,
  `head`/`tail`) free. Previously it hard-blocked all text search including
  cheap slice reads, which forced the graph onto tasks where grep is cheaper
  and blocked the grep-to-verify step the tools themselves recommend.

All three fixes below apply to both the JavaScript/TypeScript and Python
extractors (receiver capture, `new Foo()`/`Foo()` + annotation + `self`/`this`
type inference, and export/public-API awareness via `module.exports`/`export`
for JS and `__all__` + public class methods for Python).

### Fixed
- **`blast_radius` / `batch_impact` missed CommonJS importers.** The JS/TS
  parser now records `require('./x')` and dynamic `import('./x')` as IMPORTS
  edges (previously only ES `import` statements were recognized), and
  `get_blast_radius` resolves relative/dotted import specifiers to project
  files and adds direct importers to the result. Editing a file now surfaces
  the modules that `require()` it.
- **`impact` merged same-named methods on different receivers.** Call sites now
  carry the receiver expression (`app.handle` → `"app"`) and an inferred
  receiver *type*, so `find_callers` disambiguates same-named methods
  automatically. Receiver types are inferred from `new Router()`
  instantiations, TypeScript parameter/variable annotations, and class-method
  `this`; `impact "Router.handle"` then returns exactly the calls on a Router,
  name-independent, and a coincidental variable name never satisfies a typed
  query. `impact "app.handle"` filters by receiver, and every unqualified
  result row carries both `receiver` and `receiver_type` so collisions are
  fully visible. Node IDs are unchanged, so flow/trace/blast_radius are
  unaffected. (Receivers with no static type — a bare parameter later filled by
  a mixin, e.g. Express's `fn.handle` — stay name-matched; resolving those
  needs cross-function data-flow analysis.)
- **`dead_code` mis-flagged Python public API and dunder methods.** Dunder
  methods (`__call__`, `__get__`, `__getattr__`, …) are now treated as runtime
  entry points, and Python's public surface is recognized more completely —
  public (non-underscore) module-level functions and classes, not just class
  methods, are classified as public API. On a Flask ingest this cut the
  `src/flask` dead-code candidate list from 46 (37 of them public API or
  dunders) to 9 genuine underscore-private helpers.
- **`dead_code` flagged exported public API.** Definitions now track an
  `is_exported` flag from ES `export`, `module.exports = obj`, exports-object
  property assignments (`res.send = …`), chained `var app = exports =
  module.exports = {}` aliases, and `defineGetter`/`defineProperty`
  registrations. Exported symbols are classified as possible entry points
  rather than dead. (Functions reachable only via callbacks/`.bind()`/event
  emitters remain candidates — that needs data-flow analysis.)

## [2.6.2] - 2026-07-11

### Added
- CI: pushes to `main` now auto-publish to PyPI when `pyproject.toml`'s
  version changes, gated by a version-check job so routine pushes are a
  no-op (`.github/workflows/pypi-publish.yml`). This release is the first
  test of that pipeline.

## [2.6.1] - 2026-07-11

### Changed
- `AGENTS.md` broadens the re-ingest trigger from "after creating or deleting
  files" to "after any code change" (edits, additions, deletions, renames,
  refactors), so the graph stays current after routine edits too.

## [2.6.0] - 2026-07-11

### Added
- `codecompass init` (CLI and MCP) now scaffolds a `.claude/` enforcement
  layer alongside `.codecompass/`: `_ensure_claude_hooks()` writes
  `.claude/hooks/block-file-search.py` and merges the `PreToolUse` matchers
  (Bash, Grep, Glob) into `.claude/settings.json` without clobbering existing
  user hooks or settings.
- The installed hook blocks the Grep/Glob tools and code-reading shell
  commands (`cat`/`grep`/`rg`/`sed`/`awk`/`head`/`tail`/`less`) while leaving
  `ls`/`find`/`Read` open, so codebase navigation routes through the graph.
- MCP server (`mcp_server.py`) landed as `codecompass-mcp`, with tests.

## [2.5.0] - 2026-07-04

### Added
- `codecompass describe <repo_path>` — stages entity description work as batch
  files + `INSTRUCTIONS.md` under `.codecompass/describe/` for an agent swarm
  to fill in, rather than calling any single vendor's API. Any coding agent
  (Claude Code, Codex, Gemini, etc.) can dispatch its own native sub-agents
  against the staged batches, then run `describe --apply` to merge results
  into the graph and clean up. `ingest-code --describe` stages the same work
  as an optional Phase 5.
- `describe --apply` merges staged `batch_*.result.json` files into
  `.codecompass/graph.json` and removes the staging directory.
- `describe --force` allows re-staging over an in-progress run; without it,
  re-running `describe` while unmerged results exist raises an error instead
  of silently discarding them.
- AGENTS.md registration now includes an explicit "user-triggered ONLY" rule
  so agents don't run `describe` automatically after routine re-ingests.

### Changed
- `.codecompass/graph.json` is no longer gitignored — descriptions and graph
  structure are now committed so teams share the same enriched graph.
  `.codecompass/describe/` (transient staging) is gitignored instead.

## [2.4.0] - 2026-07-02

### Fixed
- PHP parsing was silently broken end-to-end: the loader called a nonexistent
  `tree_sitter_php` attribute, and the extractor matched node types from the
  wrong grammar version, so every `.php` file produced zero triples. Both are
  fixed and node types were re-verified against the installed grammar.
- Python extractor crashed ingestion on any file with a base class due to an
  undefined variable reference in the class-inheritance extraction path.

### Added
- Full PHP entity coverage: methods, properties (incl. constructor-promoted),
  class/interface/enum constants, enum cases, interfaces (multi-extends),
  traits (+ `use` composition), enums, namespace `use` imports, and
  `require`/`include`, plus every PHP call form (plain, method, nullsafe,
  static, `new`).
- `.jsx` file support in the code parser (`tree-sitter-javascript` already
  parses JSX; it was just missing from the extension/loader/extractor maps).

## [2.3.0] - 2026-07-01

### Added
- `codecompass init` now writes a "read `.codecompass` before making any changes or
  before reading any file" instruction into both `claude.md` and the `AGENTS.md` Code
  graph block, so agents surface this guidance automatically on init/re-ingest.
- PHP language support in the code parser: function/class/call extraction via
  `tree-sitter-php`, registered alongside the existing language extractors.

### Fixed
- `reader_agent.py` now only strips markdown code fences when the LLM response
  actually starts with one, instead of unconditionally.

### Removed
- Dropped the unused `chunk_pdf()` helper and its `PyPDF2` dependency.
- Dropped the unused `dry_run` parameter from `entity_resolver.resolve_entities()`.

## [2.2.0] - 2026-06-30

🚀 **The Foundation Release**

This release marks a major architectural migration to a lightweight, local-first graph structure and introduces powerful new traversal tools for AI agents and developers.

### 🌟 Key Highlights

#### 🏗️ Local-First Architecture
- **Bye-bye Neo4j**: Migrated from a heavy database dependency to a local NetworkX/JSON graph (`.codecompass/graph.json`).
- **Zero Config**: `codecompass init` now automatically initializes project state and handles `.gitignore` setup.
- **Project Memory**: Added persistent session knowledge via `.codecompass/` (overview, memory, and learnings files) to keep agents aligned across sessions.

#### 🗺️ Temporal Flow Tracing (`--flow`)
- **Execution Order**: Introduced DFS-based numbering for nodes and edges. The graph now reads as a strict sequence (Step 1 $\rightarrow$ Step 2 $\rightarrow$ Step N).
- **Multi-Format Output**: Support for Draw.io, Mermaid, and JSON.
- **Agent-Ready JSON**: Flow JSON now includes signatures, docstrings, and source snippets, allowing AI agents to narrate complex call stacks in plain English.
- **Forced Layout**: Implemented top-to-bottom vertical ranking in Mermaid for maximum readability.

#### ✂️ Dead-Code Analysis (`--dead-code`)
- Added a reachability analyzer to identify "dead" entities—functions or classes with no inbound callers or importers.
- Helps developers aggressively prune unused code with confidence.

#### 🛠️ Core Improvements
- **Metadata Enrichment**: Nodes now track `language`, `kind`, and `description` for better filtering.
- **Parser Fixes**: Improved resolution of private helper functions and method calls (`obj.method()`).
- **Clean Slate**: Fully removed all MCP-related configuration and obsolete Docker files.
