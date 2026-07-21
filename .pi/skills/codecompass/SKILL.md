---
name: codecompass
description: Orient in any indexed repo through the CodeCompass code graph before reading files. Use for discovery, impact/dependency traces, dead-code checks, and flow analysis in any repository with a .codecompass/graph.json index.
---

# CodeCompass

CodeCompass maps a repo into a queryable graph so you orient from a compact
index instead of grepping and dumping whole files. The tools are available as
MCP tools (via pi-mcp-adapter) and as the `codecompass` CLI over bash.

Orient first: start from an entry point, trace its flow and dependencies, then
read only the specific slices the graph points you to. Do not `grep`/`cat`/`rg`
across the repo to find code.

## Index / re-index

```bash
codecompass ingest-code            # run after any code change
```

## Discovery

```bash
codecompass query --tree                          # full project tree
codecompass query --grep "^get_"                  # regex over indexed entities
```

## Trace and impact

```bash
codecompass query --impact "login()"              # callers of an entity
codecompass query --blast-radius src/auth.py      # files affected by a change
codecompass query --batch-impact "foo()" "bar()"  # union blast radius
codecompass query --deps src/auth.py              # imports/dependencies
codecompass query --flow "handle_request()"       # lean flow structure
codecompass query --flow-summary "handle_request()" # mermaid + narration
codecompass query --styles LoginForm              # CSS selectors for an element
```

## Dead code

```bash
codecompass query --dead-code
codecompass query --dead-code --include-entrypoints
```

## Other

```bash
codecompass init <repo_path>       # create .codecompass/ stubs
codecompass enrich                 # stage descriptions + missing calls (user-triggered only)
codecompass enrich --apply         # merge staged enrich results into the graph
codecompass add-entity <name> --file F --line N --description "..."  # record a parser-missed entity
codecompass add-call <caller> <callee> --line N   # record a parser-missed call edge
codecompass watch                  # keep the graph updated as files change
```

## Notes

- Commands default to the current directory; pass a repo path to run elsewhere.
- `codecompass enrich` is expensive — only run it when the user explicitly asks.
- Use `add-entity`/`add-call` opportunistically while reading; entries are marked
  `agent_inferred` and survive re-ingest. Flush what you learned before re-ingesting.
- If the graph is stale (>24h), re-run `codecompass ingest-code`.
