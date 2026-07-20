# Project Overview

Read this first for orientation. For recent activity, use `git log`.

## What this repo is
**CodeCompass** is a local code knowledge-graph tool for AI coding agents. It
parses a repo into a graph (`.codecompass/graph.json`) and answers structural
questions: what calls what, blast radius before an edit, dependency direction,
dead code, and end-to-end flow tracing. Runs entirely locally — no database, no
network, no API keys required for core queries.

## Tech stack
- Python 3.10+. Install with `pip install -e .` (exposes the `codecompass` CLI).
- tree-sitter for parsing (Python, JS/TS, HTML, CSS); `networkx` for the graph,
  persisted as node-link JSON.
- Optional `anthropic` (Haiku) only for entity-name normalization.

## How to run
```bash
pip install -e .            # once, from this directory
cd /path/to/your/project
codecompass init            # creates .codecompass/ + AGENTS.md rules
codecompass ingest-code     # builds the graph (auto-runs init if needed)
codecompass query --blast-radius <file>
codecompass query --flow <symbol> --format json
codecompass query --dead-code
```

## Main entry points
- `main.py` — CLI dispatch: `init` / `ingest-code` / `enrich` / `add-entity` /
  `add-call` / `query` / `watch` / `mcp`. Also owns the AGENTS.md template and
  the generated `.claude` guard hook.
- `mcp_server.py` — FastMCP server: all query tools plus `init` / `ingest` /
  `enrich` / `add_entity` / `add_call` / `set_repo`.
- `graph/code_query_cli.py` — all query subcommands (blast-radius, impact, deps,
  grep, tree, dead-code, flow).
- `graph/code_graph_client.py` — NetworkX graph client (nodes, edges, traversal,
  `find_dead_code`).
- `ingestion/code_parser.py` — tree-sitter entity + relationship extraction.
- `ingestion/enricher.py` — agent-in-the-loop writes: `enrich` batch staging/apply,
  `add_entity` / `add_call` (all marked `agent_inferred`).
- `ingestion/source_context.py` — on-demand signature/docstring/snippet for flow.
