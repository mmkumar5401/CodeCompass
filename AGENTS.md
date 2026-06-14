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
# What should I read before editing this file?
python -m graph.code_query_cli --deps src/auth/login.py --project <name>

# What breaks if I change this function?
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
