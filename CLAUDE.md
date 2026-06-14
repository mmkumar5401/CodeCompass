# GraphRAG — Claude Code Instructions

This tool answers: **what should I read before editing X?**

It's a code dependency index backed by Neo4j. Source files are authoritative; the graph is a stale-tolerant index that degrades gracefully.

---

## Code graph queries

When asked anything about code structure, dependencies, call chains, or impact of a change, query the code graph first.

```bash
# What should I read before editing this file?
python -m graph.code_query_cli --deps ingestion/file_watcher.py --project <project>

# What breaks if I change this function?
python -m graph.code_query_cli --impact "write_code_triple" --project <project>

# Print the full folder/file hierarchy
python -m graph.code_query_cli --tree <project>

# Trace the call chain forward
python -m graph.code_query_cli --trace "main" --project <project> --hops 4
```

Output is plain text by default. Each result starts with `# index updated: <timestamp>`. If the index is older than 24 hours a `WARNING` is printed automatically — re-run `ingest-code` to refresh. If Neo4j is unreachable the CLI prints a clear error with startup instructions instead of a traceback.

> Always invoke as `python -m graph.code_query_cli` (not `python graph/code_query_cli.py`).

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
cd /Users/manojkumarmuthukumaran/Documents/Work/graphrag
python -m graph.code_query_cli --deps <file> --project graphrag
python -m graph.code_query_cli --impact "<function>" --project graphrag
python -m graph.code_query_cli --tree graphrag
```

Re-ingest after adding files:
```bash
python main.py ingest-code /Users/manojkumarmuthukumaran/Documents/Work/graphrag --project graphrag
```
<!-- graphrag-code-graph-end -->
