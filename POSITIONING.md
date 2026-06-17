# CodeCompass — Positioning Brief

**Version:** 0.2
**Date:** 2026-06-17
**Status:** Active

---

## The Problem

Every time you open an AI coding agent, it starts from zero. It doesn't know what you built last week, why you made architectural decisions, or which file to edit. You spend the first 10 minutes re-explaining your project. You watch the agent read wrong files. You answer the same questions every session. **You are the memory. And that doesn't scale.**

## The Insight

The context window is not the problem. The problem is that nothing persists when it closes. The fix isn't a bigger context window — it's memory that lives outside the context window and gets loaded back in when needed.

## The one-liner

> CodeCompass is the structural code context layer for AI agents — so they know what's connected, not just what's similar, before making any change.

---

## Positioning Brief

| Field | Value |
|---|---|
| **Target Segment** | Developers at companies running AI agents over large codebases (10k+ files) |
| **Primary JTBD** | Make complete, confident changes — ensure the agent finds every place a thing is used, doesn't read wrong files, and doesn't break hidden dependencies |
| **Category** | Structural code context for AI agents |
| **Direct Competitors** | None — category doesn't exist yet |
| **Indirect / Status Quo** | Let agent explore freely · Sourcegraph (code search, not agent-native) · DIY embedding RAG pipelines |
| **Why They Choose Us** | Team reaction: "amazed it exists." Concrete proof: token→semantic migration completed without missed usages |
| **Why They Reject / Leave** | No rejection evidence yet — primary barrier is awareness, not objection |
| **Key Differentiator** | AST-derived structural truth. Agent-native output. |

---

## Measured impact

| | Without CodeCompass | With CodeCompass |
|---|---|---|
| LLM calls per task | 2 (navigate, then edit) | 1 (edit directly) |
| Tokens per task | 26,164 | 14,210 |
| Cost per task | $1.80 | $1.27 |
| Savings | — | **−46% tokens, −30% cost** |

The biggest win: without the graph, the agent guesses which files to read and gets it wrong (one wrong file read added 9,000 tokens to a single task). The graph eliminates wrong reads entirely.

---

## The differentiation argument

### vs. Embedding RAG / Graphify / vector search

Other tools find what's **related**. CodeCompass finds what's **connected**.

Embeddings and LLM-inferred knowledge graphs return files that look similar to your query. That's useful for exploration. It's not enough for refactoring.

`file A imports file B` is not an inference — it's a fact in the syntax tree. CodeCompass reads it with tree-sitter, stores it as a typed edge (`[:IMPORTS]`, `[:CALLS]`, `[:INHERITS]`, …), and returns the complete dependency set. No approximation. No missed callers.

| | Embedding RAG / Graphify | CodeCompass |
|---|---|---|
| **Source** | Text content | AST (syntax tree) |
| **Extraction** | LLM infers relationships | tree-sitter parses facts |
| **Relationship type** | "These seem related" | "`A` imports `B`" |
| **Truth type** | Approximation | Structural fact |
| **Built for** | Human exploration | Agent navigation |

### vs. Obsidian

Obsidian is personal knowledge management — notes connected by links you create manually. The graph exists for humans to explore ideas. An AI agent can't usefully query it about code structure. Different domain entirely.

### vs. Sourcegraph

Sourcegraph is code search — find where a symbol appears as text. CodeCompass is dependency traversal — find every file connected to a symbol through typed edges. Sourcegraph tells you where `writeCodeTriple` is mentioned. CodeCompass tells you every caller, transitively, three hops deep.

---

## The two differentiators

### 1. The AST doesn't lie

> *"Other tools find what's related. CodeCompass finds what's connected."*

Every other approach — embeddings, LLM extraction, keyword search — derives relationships from reading text. CodeCompass derives them from the syntax tree. This distinction is critical when the cost of missing one file is a broken build or a partial migration.

### 2. Built for agents, not humans

> *"It doesn't show you the graph. It gives the graph to the agent."*

Obsidian and Graphify produce visualisations and chat interfaces for human exploration. CodeCompass produces an MCP server — the code graph becomes native tools (`blast_radius`, `impact`, `deps`, …) in the agent's tool palette, available from any working directory. Instructions mandate graph-first queries. Session memory accumulates automatically via the plugin. Every design decision assumes the consumer is an LLM, not a human browsing a UI.

---

## Proof point

Token-to-semantic migration across a large codebase. The agent queried the graph before making changes — found every file that referenced the old tokens, changed them all. No missed usages. No broken files discovered later.

This is the sharpest demonstration of the JTBD: **the agent made a complete change, not just a confident one.**

---

## What we are not

- Not a knowledge graph for documents or notes (that's Graphify, Obsidian)
- Not code search (that's Sourcegraph, grep.app)
- Not a RAG pipeline (we're the replacement for the retrieval step, not the full pipeline)
- Not an IDE plugin (output is for agents, not developers browsing code)
- Not a team collaboration tool (single-developer or single-agent tool today)

---

## Current state

- **MCP server** — 8 tools (blast_radius, impact, deps, trace, tree, styles, batch_impact, list_projects) exposed as native agent tools
- **opencode plugin** — session memory auto-saves on compaction + idle
- **Instructions** — graph-first rules loaded into every session
- **One-command setup** — `./install.sh` from clone to working in minutes
- **Measured** — 46% token reduction, 30% cost reduction on realistic tasks
- **Open source** — runs locally, your data stays on your machine

---

## Roadmap priorities (from feature audit)

Ranked by RICE score against confirmed positioning:

| Priority | Feature | Rationale tag | RICE | Status |
|---|---|---|---|---|
| 1 | **Blast radius preview** | `supports-JTBD` `differentiator` | 84 | ✅ Done |
| 2 | **Batch impact analysis** | `supports-JTBD` | 80 | ✅ Done |
| 3 | **MCP server** | `differentiator` `category-hygiene` | 64 | ✅ Done |
| 4 | **Git diff integration** | `supports-JTBD` `differentiator` | 48 | — |
| 5 | **Language expansion** (Go, Java, Rust) | `category-hygiene` | 30/lang | —

**Blocked (insufficient evidence or cost):**
- VS Code extension — no evidence agents need a GUI
- Cross-repo graph — XL effort, no confirmed demand
- Team / cloud sync — XL effort, no confirmed demand
- Natural language query — assumption-dependent, validate first

---

## Category creation strategy

The category ("structural code context for AI agents") does not exist yet. No buyer has a mental shelf for it. This is both the opportunity (define it, own it) and the primary challenge (explain it from scratch every time).

**Implication for near-term focus:**
- The product must create a "wow, I didn't know this existed" moment on first encounter — the MCP integration achieves this (tools appear alongside `read`, `edit`, `bash`)
- The migration proof point is the wedge: lead with a concrete before/after story, not a feature list
- MCP server shipped — any MCP-compatible agent can now call CodeCompass via `pip install codecompass-mcp`

---

## The vision

AI coding agents are already powerful engineering assistants. The missing piece is continuity.

CodeCompass is the layer that makes agents remember — across every session, every project, every machine, every team member. A developer using CodeCompass for six months has an assistant that knows their entire codebase, every architectural decision, every paper they've read, every pattern they've established. That assistant gets *more* useful over time, not the same.

The product: **an AI coding agent with a memory that compounds.**

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-06-17 | MCP server shipped, opencode plugin, one-command setup, multi-agent positioning |
| 0.1 | 2026-06-14 | Initial brief — segment, JTBD, category, differentiators confirmed |
