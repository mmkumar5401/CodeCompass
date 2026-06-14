# GraphRAG — Project Overview

Neo4j-backed code dependency index. Answers: **what should I read before editing X?**
Neo4j at `bolt://localhost:7687` (configurable via `.env`).

## Code graph

File/function structure of any ingested codebase.
- Nodes: Project → Folder → File → Entity (function/class/import)
- Typed edges: `[:CALLS]`, `[:IMPORTS]`, `[:INHERITS]`, `[:STYLES]`, …
- Query with: `python -m graph.code_query_cli --deps file.py --project <name>`

## Core value

Eliminates the navigation step: instead of reading 2–3 wrong files to orient, Claude queries the graph and goes directly to the right file.

## Key rule

Query the code graph before making any code change. See CLAUDE.md for the query commands.
