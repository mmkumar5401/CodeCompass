# GraphRAG — Claude Code Instructions

This tool answers: **what should I read before editing X?**

It's a code dependency index backed by Neo4j. Source files are authoritative; the graph is a stale-tolerant index that degrades gracefully.

---

## Code graph queries

When asked anything about code structure, dependencies, call chains, or impact of a change, query the code graph first.

```bash
# What should I read before editing this file or symbol?
python -m graph.code_query_cli --blast-radius ingestion/file_watcher.py --project <project>
python -m graph.code_query_cli --blast-radius "write_code_triple" --project <project>

# Planning a multi-file change — what does the whole set touch?
python -m graph.code_query_cli --batch-impact ingestion/file_watcher.py graph/code_graph_client.py --project <project>

# What does this file import (direct + transitive)?
python -m graph.code_query_cli --deps ingestion/file_watcher.py --project <project>

# What breaks if I change this function?
python -m graph.code_query_cli --impact "write_code_triple" --project <project>

# Print the full folder/file hierarchy
python -m graph.code_query_cli --tree <project>

# Trace the call chain forward
python -m graph.code_query_cli --trace "main" --project <project> --hops 4

# What CSS selectors style this element?
python -m graph.code_query_cli --styles MyComponent --project <project>
```

Output is plain text by default. Each result starts with `# index updated: <timestamp>`. If the index is older than 24 hours a `WARNING` is printed automatically — re-run `ingest-code` to refresh. If Neo4j is unreachable the CLI prints a clear error with startup instructions instead of a traceback.

> Always invoke as `python -m graph.code_query_cli` (not `python graph/code_query_cli.py`).

### When to use which flag

| Scenario | Command |
|---|---|
| About to edit one file or symbol | `--blast-radius` first |
| Planning a PR touching N files | `--batch-impact file1 file2 ...` |
| Renaming or removing a function | `--impact FunctionName` |
| Understanding what a file pulls in | `--deps path/to/file` |
| Tracing a call chain forward | `--trace EntryPoint` |
| Orienting in an unfamiliar project | `--tree <project>` |
| Editing a CSS variable or component | `--styles ElementName` |

### What the graph can answer

- All files touched by a proposed change (`--blast-radius`, `--batch-impact`)
- Which files does this file depend on? (`--deps`)
- What would break if this function changes? (`--impact`)
- What's the call chain from this entry point? (`--trace`)
- What CSS selectors style this element? (`--styles`)

### What it cannot answer

- What code *means* or whether it's correct — structure only, not semantics
- Anything in un-ingested repos or unsupported languages (Python, JS, TS, TSX, HTML, CSS, SCSS, `.styles.ts` are all supported)
- Callers outside the ingested repo (external consumers won't appear in `--impact`)
- Current state if files were edited without the watcher running

### Ingested file types

| Language | Edges emitted |
|---|---|
| Python, JS, TS, TSX | `CALLS`, `IMPORTS`, `INHERITS` |
| CSS, SCSS | `DEFINED_IN` (variable declarations), `USES_VAR` (usages), `IMPORTS` (@import/@use) |
| HTML | `REFERENCES` (custom element tags), `INCLUDES` (script/link) |
| `.styles.ts` (Lit) | `USES_VAR` (var() inside css`...` blocks), `DEFINED_IN` (--prop declarations) + all normal TS edges |

> **Lit design tokens:** `--impact "--tm-button-block-size" --project <name>` now returns every `.styles.ts` file that consumes a token — the secondary CSS extraction pass runs automatically on any file ending in `.styles.ts`.

---

## Ingestion

```bash
# Full ingest (no LLM normalization by default — fast and reliable)
python main.py ingest-code /path/to/repo --project <name>

# With Haiku normalization (slower, requires API credits)
python main.py ingest-code /path/to/repo --project <name> --normalize

# Watch for live changes in a separate terminal
python main.py watch /path/to/repo --project <name>
```

---

## Storing session decisions

Write non-obvious architectural decisions to `memory/decisions.md` (plain Markdown, dated entries):

```markdown
## YYYY-MM-DD: <short title>
Reason: <why this decision was made>
Impact: <what changes if this is reversed>
```

Search it with `rg <keyword> memory/decisions.md`.

Do **not** write graph triples after every response — the file watcher handles incremental updates automatically.

---

## If the graph is empty

```bash
python main.py ingest-code . --project graphrag
```

---

## Storing a session

When the user says "store my session", append discoveries to `memory/learnings.md`:

```markdown
## YYYY-MM-DD
- <specific learning — design decision, bug found, constraint discovered>
```

Max 8 bullets. Skip routine edits and obvious code details.

---

<!-- graphrag-code-graph-start -->
## Code graph

This project is indexed in the GraphRAG code graph as `graphrag`. Query it before editing to know what to read:

```bash
# Run from the graphrag repo root
python -m graph.code_query_cli --deps <file> --project graphrag
python -m graph.code_query_cli --impact "<function>" --project graphrag
python -m graph.code_query_cli --tree graphrag
```

Re-ingest after adding files:
```bash
python main.py ingest-code . --project graphrag
```
<!-- graphrag-code-graph-end -->
