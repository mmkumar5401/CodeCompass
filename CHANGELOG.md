# Changelog

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
