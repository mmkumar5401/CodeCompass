# CodeCompass — Agent Instructions

A local code dependency graph lives in `.codecompass/graph.json` at the root of this repository. **Always query it before editing code.** The graph knows what's connected — trust it over file exploration.

---

## How to query the graph

Run queries with the CLI using your `bash` tool:

```bash
# What files are affected if I change this file or symbol?
python -m graph.code_query_cli --blast-radius <file_or_symbol> <repo_path>

# What calls or uses a function/class? (before renaming or removing)
python -m graph.code_query_cli --impact <symbol> <repo_path>

# What does a file import, directly and transitively?
python -m graph.code_query_cli --deps <file_path> <repo_path>

# Forward call chain from a function
python -m graph.code_query_cli --trace <function_name> <repo_path>

# Full project structure
python -m graph.code_query_cli --tree <repo_path>

# CSS selectors that target an element
python -m graph.code_query_cli --styles <element_name> <repo_path>

# Union blast radius across multiple files (planning a multi-file PR)
python -m graph.code_query_cli --batch-impact <file1> <file2> <repo_path>
```

---

## When to use each query

| Scenario | Command |
|---|---|
| About to edit one file or symbol | `--blast-radius` first |
| Planning a PR touching N files | `--batch-impact` |
| Renaming or removing a function | `--impact` |
| Understanding what a file imports | `--deps` |
| Tracing a call chain forward | `--trace` |
| Orienting in an unfamiliar project | `--tree` |
| Finding which CSS targets an element | `--styles` |

---

## Mandatory rules

1. **Before editing any file in this project, run a graph query first.**
2. Use `--blast-radius` to understand what else you'll affect.
3. Use `--impact` before renaming or removing anything.
4. If the output includes a `WARNING: Nh old`, the index is stale — suggest re-running `codecompass ingest-code <repo_path>`.
5. The graph reflects **structural truth** from the AST. It tells you what's connected, not what code means.

---

## Project memory

Session learnings are stored in `.codecompass/learnings.md`. Architectural context is in `.codecompass/memory.md`. Read them at session start if relevant to your task.
