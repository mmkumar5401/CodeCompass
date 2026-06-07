# GraphRAG — Project Overview

Neo4j-backed persistent knowledge graph that acts as long-term memory for LLMs.
Project root: `/Users/manojkumarmuthukumaran/Documents/Work/graphrag`
Neo4j at `bolt://localhost:7687`.

## Two separate graphs

**Doc graph** — concepts extracted from papers and documents
- Nodes: `(:Entity {id, name, type})`
- Edges: `-[:RELATION {type, weight, session_id, created_at}]->`
- Query with: `python graph/query_cli.py "question" --hops 2`

**Code graph** — file/function structure of ingested codebases
- Nodes: Project → Folder → File → Entity (function/class/import)
- Query with: `python -m graph.code_query_cli --deps file.py --project <name> --plain`

## Core value

Eliminates the navigation step: without the graph, Claude reads 2–3 wrong files before finding the right one. With the graph, it goes directly to the correct file. Eval result: **−46% tokens, −30% cost** on realistic edit tasks.

## Key rule

Always query the knowledge graph before answering any question or making any code change. See CLAUDE.md for the mandatory query commands.
