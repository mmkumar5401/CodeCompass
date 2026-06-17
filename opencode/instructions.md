# CodeCompass — opencode Instructions

A Neo4j-backed code dependency graph is available via MCP tools. **Always query it before editing code.** The graph knows what's connected — trust it over file exploration.

---

## Available tools (MCP)

All tools use the `codecompass` MCP server. Call them from any working directory.

| Tool | Purpose |
|---|---|
| `list_projects` | See all ingested projects |
| `blast_radius` | Every file a symbol/file touches (forward) |
| `impact` | What calls/uses a symbol (reverse) |
| `deps` | What a file imports |
| `trace` | Forward call chain from a function |
| `tree` | Folder/file hierarchy |
| `styles` | CSS selectors for an element |
| `batch_impact` | Union blast radius across N targets |

---

## When to use each tool

| Scenario | Tool to call first |
|---|---|
| About to edit one file or symbol | `blast_radius(symbol, project)` |
| Planning a PR touching N files | `batch_impact("file1, file2", project)` |
| Renaming or removing a function | `impact(function_name, project)` |
| Understanding what a file imports | `deps(file_path, project)` |
| Tracing a call chain forward | `trace(entry_point, project)` |
| Orienting in an unfamiliar project | `tree(project)` |
| Finding which CSS targets an element | `styles(element_name, project)` |
| Discovering ingested projects | `list_projects()` |

---

## Mandatory rules

1. **Before editing any file in an ingested project, call the codecompass tools first.**
2. Use `list_projects()` to discover what projects are available.
3. Use `blast_radius` to understand impact before making changes.
4. Use `impact` before renaming or removing anything.
5. If a tool returns a WARNING about stale index, suggest re-running `ingest-code`.
6. The graph provides **structural truth** (AST-parsed). Trust it. It cannot tell you what code *means* — only what's connected.

---

## Project memory

Session learnings are stored in `memory/learnings.md`. Design decisions are in `memory/decisions.md`. These accumulate across sessions — read them at session start if relevant to your task.
