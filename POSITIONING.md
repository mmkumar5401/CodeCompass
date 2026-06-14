# GraphRAG — Positioning Brief

**Version:** 0.1
**Date:** 2026-06-14
**Status:** Confirmed

---

## The one-liner

> GraphRAG is the structural code context layer for AI agents — so they know what's connected, not just what's similar, before making any change.

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

## The differentiation argument

### vs. Embedding RAG / Graphify / vector search

Other tools find what's **related**. GraphRAG finds what's **connected**.

Embeddings and LLM-inferred knowledge graphs return files that look similar to your query. That's useful for exploration. It's not enough for refactoring.

`file A imports file B` is not an inference — it's a fact in the syntax tree. GraphRAG reads it with tree-sitter, stores it as a typed edge (`[:IMPORTS]`, `[:CALLS]`, `[:INHERITS]`, …), and returns the complete dependency set. No approximation. No missed callers.

| | Embedding RAG / Graphify | GraphRAG |
|---|---|---|
| **Source** | Text content | AST (syntax tree) |
| **Extraction** | LLM infers relationships | tree-sitter parses facts |
| **Relationship type** | "These seem related" | "`A` imports `B`" |
| **Truth type** | Approximation | Structural fact |
| **Built for** | Human exploration | Agent navigation |

### vs. Obsidian

Obsidian is personal knowledge management — notes connected by links you create manually. The graph exists for humans to explore ideas. An AI agent can't usefully query it about code structure. Different domain entirely.

### vs. Sourcegraph

Sourcegraph is code search — find where a symbol appears as text. GraphRAG is dependency traversal — find every file connected to a symbol through typed edges. Sourcegraph tells you where `writeCodeTriple` is mentioned. GraphRAG tells you every caller, transitively, three hops deep.

---

## The two differentiators

### 1. The AST doesn't lie

> *"Other tools find what's related. GraphRAG finds what's connected."*

Every other approach — embeddings, LLM extraction, keyword search — derives relationships from reading text. GraphRAG derives them from the syntax tree. This distinction is critical when the cost of missing one file is a broken build or a partial migration.

### 2. Built for agents, not humans

> *"It doesn't show you the graph. It gives the graph to the agent."*

Obsidian and Graphify produce visualisations and chat interfaces for human exploration. GraphRAG produces plain-text dependency lists the agent can act on immediately. Every design decision (CLI-first, plain text default, CLAUDE.md auto-registration, watcher PID tracking) assumes the consumer is a machine.

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

## Roadmap priorities (from feature audit)

Ranked by RICE score against confirmed positioning:

| Priority | Feature | Rationale tag | RICE |
|---|---|---|---|
| 1 | **Blast radius preview** | `supports-JTBD` `differentiator` | 84 |
| 2 | **Batch impact analysis** | `supports-JTBD` | 80 |
| 3 | **MCP server** | `differentiator` `category-hygiene` | 64 |
| 4 | **Git diff integration** | `supports-JTBD` `differentiator` | 48 |
| 5 | **Language expansion** (Go, Java, Rust) | `category-hygiene` | 30/lang |

**Blocked (insufficient evidence or cost):**
- VS Code extension — no evidence agents need a GUI
- Cross-repo graph — XL effort, no confirmed demand
- Team / cloud sync — XL effort, no confirmed demand
- Natural language query — assumption-dependent, validate first

---

## Category creation strategy

The category ("structural code context for AI agents") does not exist yet. No buyer has a mental shelf for it. This is both the opportunity (define it, own it) and the primary challenge (explain it from scratch every time).

**Implication for near-term focus:**
- The product must create a "wow, I didn't know this existed" moment on first encounter — it already does (team reaction evidence)
- The migration proof point is the wedge: lead with a concrete before/after story, not a feature list
- MCP server is the highest-leverage move for category definition: when any agent in any tool can call GraphRAG, the category becomes self-evident

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-06-14 | Initial brief — segment, JTBD, category, differentiators confirmed |
