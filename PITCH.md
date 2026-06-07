# GraphRAG — Pitch Deck

---

## The Problem

Every time you open Claude Code, it starts from zero.

It doesn't know what you built last week. It doesn't know why you made that architectural decision. It doesn't know that the `neo4j_client.py` file is the one to edit for connection changes — not `code_graph_client.py`. It doesn't know the paper you read last month that directly explains what your code is doing.

You spend the first 10 minutes of every session re-explaining your project. Then you watch Claude read 3 wrong files before finding the right one. Then you answer the same questions you answered yesterday.

**You are the memory. And that doesn't scale.**

---

## The Insight

The context window is not the problem. The problem is that nothing persists when it closes.

LLMs are powerful reasoners. They just have no long-term memory. Every session is the first session. Every project is unknown territory. Every decision has to be re-explained.

The fix isn't a bigger context window. It's a memory that lives outside the context window and gets loaded back in when needed.

---

## What GraphRAG Is

GraphRAG is a persistent memory layer for Claude Code.

It gives Claude a structured, growing knowledge base about your projects — your code structure, your documents, your design decisions, your past sessions — and makes that knowledge available automatically at the start of every session.

**Two memory systems working together:**

A **file memory** layer (`memory/`) that stores human-readable markdown — project context, design decisions, accumulated learnings. Injected into every session automatically before you type your first message.

A **knowledge graph** (Neo4j) that stores structured facts as typed relationships — entities connected by semantics. Your code's dependency graph. Concepts from papers and documents. Links between ideas across sessions. Queryable in natural language, zero API cost.

---

## How It Works

```
You open a session (any directory, any project)
        ↓
SessionStart hook fires — memory/ injected before your first message
        ↓
Claude already knows your project
        ↓
You edit a file
        ↓
PostToolUse hook fires — code graph updated instantly
        ↓
Claude always has current dependency and structure info
        ↓
You say "store my session" when it was a productive session
        ↓
Claude reviews the conversation, extracts key insights
        ↓
Learnings written to memory/learnings.md — zero API cost
        ↓
Session closes — Stop hook logs metadata to session_log.md
```

The automation handles the routine. You control when insights are worth keeping.

---

## The Numbers

We measured token usage on realistic code tasks — the same tasks run with and without the graph, without mounting the project folder (simulating Claude Code in a fresh environment).

| | Without GraphRAG | With GraphRAG |
|---|---|---|
| LLM calls per task | 2 (navigate, then edit) | 1 (edit directly) |
| Tokens per task | 26,164 | 14,210 |
| Cost per task | $1.80 | $1.27 |
| Savings | — | **−46% tokens, −30% cost** |

The biggest win: without the graph, Claude guesses which files to read and gets it wrong. One wrong file read added 9,000 tokens to a single task. The graph eliminates wrong reads entirely.

---

## What You Get

**You stop being the memory.**
Claude knows your codebase. It knows your decisions. It knows your documents. It knows what you worked on yesterday.

**Sessions compound instead of reset.**
Every session makes the next one smarter. Learnings accumulate. The graph grows. The more you use it, the better it gets.

**Code navigation without exploration.**
Claude goes directly to the file that needs changing. No reading the directory tree. No reading wrong files. No asking you where things live.

**Documents become queryable knowledge.**
Ingest a paper, an architecture doc, a Slack thread. It becomes part of the graph — queryable, relatable to other concepts, surfaced when relevant.

**Portable across machines.**
Memory lives in the repository. Clone the repo on a new machine and Claude has full context immediately. Your team gets the same memory you built.

---

## What Makes This Different

Most "memory for AI" products store chunks of text and retrieve the most similar ones. That's vector search — useful for finding relevant passages, not for understanding structure.

GraphRAG stores *relationships*. Not just what things are — but how they connect.

- `neo4j_client.py` **IMPLEMENTS** `connection pooling`
- `connection pooling` **DESCRIBED_BY** `the architecture doc you ingested`
- `architecture doc` **REFERENCES** `the paper on distributed graph traversal`

Claude can follow that chain. It can answer "how does our connection pooling relate to the paper I read?" because the graph links them — not because they appeared in the same chunk of text.

---

## The Vision

Claude Code is already a powerful engineering assistant. The missing piece is continuity.

GraphRAG is the layer that makes Claude Code remember — not just within a session, but across every session, every project, every machine, every team member.

A developer who has used Claude Code with GraphRAG for six months has an assistant that knows their entire codebase, every architectural decision they've made, every paper they've read, every pattern they've established. That assistant gets *more* useful over time, not the same.

That's the product: **Claude Code with a memory that compounds.**

---

## Current State

- **Working** — file memory, code graph, doc graph, all three auto-hooks
- **Measured** — 46% token reduction, 30% cost reduction on realistic tasks
- **Open source** — runs locally, your data stays on your machine
- **One-command setup** — `./install.sh` gets you from clone to working in minutes

---

## Get Started

```bash
git clone https://github.com/mmkumar5401/GraphRag
cd GraphRag
./install.sh
claude
```

Your next session will be smarter than your last.
