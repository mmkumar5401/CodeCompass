<!-- codecompass-code-graph-start -->
## Code graph

This project has a CodeCompass code knowledge graph at `.codecompass/graph.json`.
Every node carries `kind` (e.g. `function:python`, `class:typescript`) and a
human-readable `description`. Use it as your primary navigation tool.

All commands default to the current directory — run them from the project root.

### Rules — MUST follow

1. **Before editing any file**, run `--blast-radius` on it to see what depends on it:
   ```bash
   codecompass query --blast-radius <file_or_symbol>
   ```
2. **Before calling or importing a symbol you haven't read**, run `--impact` to
   understand its downstream effects:
   ```bash
   codecompass query --impact <symbol>
   ```
3. **After creating or deleting files**, re-ingest so the graph stays current:
   ```bash
   codecompass ingest-code
   ```
4. **Never skip step 1.** Reading a file without checking its blast radius first
   means you may miss callers, importers, or CSS/HTML dependents.

### Available queries

| Command | Purpose |
|---|---|
| `codecompass query --blast-radius <file_or_symbol>` | All nodes affected if you change this |
| `codecompass query --impact <symbol>` | Downstream callers / importers of a symbol |
| `codecompass query --deps <file>` | What this file depends on |
| `codecompass query --tree` | Full project structure with entity types |
| `codecompass query --dead-code` | Find functions/classes with no caller or importer (candidates to remove) |
| `codecompass query --flow <entry_symbol>` | Trace a call/import flow from an entry point (draw.io diagram by default) |
| `codecompass query --flow <entry_symbol> --format mermaid` | Same trace as a Markdown mermaid flowchart (renders on GitHub) |
| `codecompass query --flow <entry_symbol> --format json` | Same trace enriched with signatures, docstrings, and source snippets |

### Explaining how something works

When asked to explain a pipeline, feature, or "what happens when X", do NOT
guess from file names. Trace it:

```bash
codecompass query --flow <entry_symbol> --format json
```

The JSON (written to `.codecompass/flow_<entry>.json`) gives you, for every
function in the flow: its real signature, docstring, source snippet, and the
ordered call sites (the `order` field on each edge is the call sequence by
source line). Narrate the data flow from the entry point downward — describe
what data enters and leaves each function using the signatures and docstrings,
and explain the transformations from the source snippets.

### Finding dead code

`codecompass query --dead-code` lists entities with no inbound caller or
importer — candidates for removal (old helpers, superseded versions, orphaned
scripts). Results are split into "likely dead" and (with `--include-entrypoints`)
"possible entry points".

This is STATIC analysis: dynamic dispatch, reflection, and string-based
invocation are invisible. Treat every result as a candidate — grep the name
across the repo to confirm it is truly unused before deleting it.

### When to re-ingest

- After adding, renaming, or deleting source files
- After major refactors (moved functions, renamed classes)
- If query results look stale or incomplete
<!-- codecompass-code-graph-end -->
