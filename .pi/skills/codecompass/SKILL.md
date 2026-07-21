---
name: codecompass
description: Orient in any indexed repo through the CodeCompass code graph before reading files. Use for discovery, impact/dependency traces, dead-code checks, and flow analysis in any repository with a .codecompass/graph.json index.
---

# CodeCompass

CodeCompass maps a repo into a queryable graph so you orient from a compact
index instead of grepping and dumping whole files. The graph is queried ONLY
through the codecompass MCP tools — there is no agent-facing CLI.

Orient first: start from an entry point, trace its flow and dependencies, then
read only the specific slices the graph points you to. Do not `grep`/`cat`/`rg`
across the repo to find code.

The server defaults to the current directory; call `codecompass_set_repo` to
point it at another repo.

## Index / re-index

- `codecompass_ingest` — run after any code change

## Discovery

- `codecompass_tree` — full project tree
- `codecompass_grep` — regex over indexed entities, e.g. `pattern="^get_"`

## Trace and impact

- `codecompass_impact` — callers of an entity
- `codecompass_blast_radius` — files affected by a change to a file/symbol
- `codecompass_batch_impact` — union blast radius across targets
- `codecompass_deps` — imports/dependencies of a file
- `codecompass_flow` — lean flow structure from an entry point
- `codecompass_flow_summary` — mermaid + narration, `format="json"` embeds signatures/source
- `codecompass_styles` — CSS selectors for an element
- `codecompass_dead_code` — entities with no inbound caller (`include_entrypoints=True` to also list entry points)

## Recording what the parser missed

- `codecompass_add_entity` — record a parser-missed entity (kind, file, line, description)
- `codecompass_add_call` — record a parser-missed call edge

## Notes

- `codecompass_enrich` is expensive — only run it when the user explicitly asks.
  Merge staged results with `codecompass_enrich(apply=True)`.
- Use `add_entity`/`add_call` opportunistically while reading; entries are marked
  `agent_inferred` and survive re-ingest. Flush what you learned before re-ingesting.
- If the graph looks stale or incomplete, re-run `codecompass_ingest`.
