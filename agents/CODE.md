# Code Agent

Use this when the task involves editing, adding, or understanding code structure.

---

## Operations

### Edit or extend a file

```bash
# 1. Find what the file depends on
python -m graph.code_query_cli --deps <file_path> --project <project> --plain

# 2. Read only the files identified as internal dependencies
# 3. Make the edit
```

**Example:**
```bash
python -m graph.code_query_cli --deps ingestion/file_watcher.py --project graphrag --plain
# → reads ingestion/code_parser.py, graph/code_graph_client.py
# → now you know what patterns and types are available before editing
```

---

### Understand impact before changing something

```bash
python -m graph.code_query_cli --impact <function_or_class> --project <project> --plain
```

Use this before renaming, removing, or changing the signature of anything.
If callers exist, read those files too before making the change.

---

### Trace a call chain

```bash
python -m graph.code_query_cli --trace <entry_point> --project <project> --hops 4 --plain
```

Use when you need to understand the full execution path from an entry point
(e.g., tracing what happens when `main.py ingest-code` is called).

---

### Browse project structure

```bash
python -m graph.code_query_cli --tree <project> --plain
```

Use when you need to find where something lives before reading files.
Cheaper than listing directories recursively.

---

### Create a new file or module

1. Run `--tree` to understand where similar files live
2. Run `--deps` on the most similar existing file to understand what to import
3. Create the new file following the same import patterns

---

## Rules

- Always run `--deps` before editing — never guess imports cold
- Always run `--impact` before renaming or removing anything
- Read only the files the graph identifies — do not read the entire directory
- If `--deps` returns only stdlib/third-party modules, read just the target file itself
- Use `--plain` flag always — rich table output wastes tokens
