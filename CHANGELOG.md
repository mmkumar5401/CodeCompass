# Changelog

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
