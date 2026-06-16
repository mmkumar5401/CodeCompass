# GraphRAG — Agent Instructions

This tool answers one question: **what should I read before editing X?**

It's a dependency index backed by Neo4j. Source files are authoritative; the graph is a stale-tolerant index that degrades gracefully.

---

## 1. Setup

```bash
# Start Neo4j (Docker)
docker compose up -d

# Configure credentials
cp .env.example .env
# Edit .env: set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, ANTHROPIC_API_KEY

# Ingest a codebase (plain text output, no LLM normalization)
python main.py ingest-code /path/to/repo --project <name>
```

---

## 2. Query

```bash
# Before editing a file or symbol — see everything it touches (forward traversal)
python -m graph.code_query_cli --blast-radius src/auth/login.py --project <name>
python -m graph.code_query_cli --blast-radius "write_code_triple" --project <name>

# Before a multi-file change or PR — union blast radius across all targets
python -m graph.code_query_cli --batch-impact src/auth/login.py src/auth/session.py --project <name>

# What does this file import (direct + transitive)?
python -m graph.code_query_cli --deps src/auth/login.py --project <name>

# What breaks if I change this function? (reverse traversal)
python -m graph.code_query_cli --impact "write_code_triple" --project <name>

# Print the full folder/file hierarchy
python -m graph.code_query_cli --tree <name>

# Trace the call chain forward from a function
python -m graph.code_query_cli --trace "main" --project <name> --hops 4

# What CSS selectors style this element?
python -m graph.code_query_cli --styles "LoginForm" --project <name>
```

Output is plain text by default. Add `--rich` for formatted tables (human use only).

> Always invoke as `python -m graph.code_query_cli` (not `python graph/code_query_cli.py`) to avoid module import errors.

### When to use which flag

| Scenario | Flag |
|---|---|
| About to edit one file or symbol | `--blast-radius` first |
| Planning a PR touching N files | `--batch-impact file1 file2 ...` |
| Renaming or removing a function | `--impact FunctionName` |
| Understanding what a file imports | `--deps path/to/file` |
| Tracing a call chain forward | `--trace EntryPoint` |
| Orienting in an unfamiliar project | `--tree <project>` |
| Editing a CSS variable or component | `--styles ElementName` |

### Ingested file types

| Language | Edges emitted |
|---|---|
| Python, JS, TS, TSX | `CALLS`, `IMPORTS`, `INHERITS` |
| CSS, SCSS | `DEFINED_IN` (variable declarations), `USES_VAR` (usages), `IMPORTS` (@import/@use) |
| HTML | `REFERENCES` (custom element tags with hyphen), `INCLUDES` (script/link tags) |
| `.styles.ts` (Lit) | `USES_VAR` (var() in css`...` blocks), `DEFINED_IN` (--prop declarations) + all normal TS edges |

> **Lit design tokens:** use `--impact "--tm-button-block-size" --project <name>` to find every `.styles.ts` that consumes a token. The secondary CSS extraction pass runs automatically — no extra flags needed.

---

## 3. If the graph is empty or stale

Re-run ingest-code:

```bash
python main.py ingest-code /path/to/repo --project <name>
```

To keep the graph fresh while editing, run the watcher in a separate terminal:

```bash
python main.py watch /path/to/repo --project <name>
```

To dump raw triples for external normalization instead of writing directly:

```bash
python main.py ingest-code /path/to/repo --project <name> --dump-triples /tmp/raw.json
# normalize /tmp/raw.json externally, then:
python main.py load-triples /tmp/normalized.json --project <name>
```

---

## Notes

- Each query result includes `# index updated: <timestamp>`. If older than 24 hours, a `WARNING` line is printed automatically — re-run `ingest-code` to refresh.
- If Neo4j is not running, queries print a clear error with startup instructions (`docker compose up -d`) instead of a Python traceback.
- Write to `memory/decisions.md` when you make a non-obvious architectural decision. Plain Markdown, dated entries, searched with `rg`.
- Do not write graph triples after every response — the file watcher handles incremental updates automatically.
