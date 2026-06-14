# Design Decisions

Format: dated entries. Search with `rg <keyword> memory/decisions.md`.

---

## 2026-06-14: Switched to typed Neo4j relationships

Reason: Generic `[:RELATION {type: 'CALLS'}]` on variable-length paths can't be index-scanned by Neo4j Community. On large repos, `--impact` queries would blow up.
Impact: Re-ingest required after this change. Any graph written before 2026-06-14 uses the old schema and will return wrong results with the new Cypher queries.
How: `write_code_triple()` now uses string-interpolated typed rels (`[:CALLS]`, `[:IMPORTS]`, etc.) with whitelist validation in `_ALLOWED_REL_TYPES`.

## 2026-06-14: Folded db_router.py into code_graph_client.py

Reason: The "auto/master/project" routing scheme solved a multi-database problem we don't have. The only useful thing was `project_client(name)`, now replaced by `get_client(project)` at module level in `code_graph_client.py`.
Impact: All code that previously imported `from graph.db_router import project_client` now imports `from graph.code_graph_client import get_client`.

## 2026-06-14: Plain text is now the default output mode

Reason: Agents don't opt into plain text — they need it unconditionally. Rich table output inflated context ~2.7x. The old `--plain` flag was easy to forget.
Impact: `--plain` flag removed. Use `--rich` to get formatted tables (human use only).

## 2026-06-14: --normalize is now opt-in (was --skip-normalize)

Reason: Haiku normalization is a latency spike + failure mode in the middle of ingestion. "Boringly reliable" means the default path has no LLM calls.
Impact: `python main.py ingest-code` now skips normalization by default. Pass `--normalize` to enable the Haiku pass.

## 2026-06-14: --deps before --impact

`--deps path/to/file.py` always returns useful import/dependency info.
`--impact FunctionName` returns "Nothing calls X" for functions not called externally — misleading for internal helpers.
Rule: default to `--deps`. Add `--impact` only when checking callers before renaming/removing.

## 2026-06-14: on_moved handler added to FileWatcher

Reason: watchdog's default `on_moved` is a no-op. Without it, renaming a file left ghost File+Entity nodes under the old path forever.
Impact: `_remove_file_from_graph()` now calls `client.delete_file()` (not `delete_file_triples()`) to clean up both Entity nodes and the File node on delete/move. `delete_file_triples()` is still used on modify (keeps the File node, re-populates entities).

## 2026-06-14: Community Neo4j with project property isolation

Reason: Enterprise licensing is not worth it for a single-user tool. Community edition supports one default database; projects are isolated via the `project` property on nodes.
Impact: `get_client()` passes `database=None` — Neo4j uses the default database. All queries include `project: $project` filters.
