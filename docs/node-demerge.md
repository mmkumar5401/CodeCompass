# Node-level de-merge

## Problem

Graph nodes are keyed by name only — `f"{project}:{name.lower()}"` — so every
entity that shares a name collapses into one node. `api.request` and
`Session.request` become a single `project:request` node; `Session.send`,
`HTTPAdapter.send`, `BaseAdapter.send` become one `project:send`. The merged
node's `file` is last-writer-wins, so `impact`/`flow`/`blast_radius` report the
wrong file, and callers of *different* same-named methods pile onto one node.

## Design

### 1. File-qualified node identity
An entity's node id becomes `project:{source_file}:{name}` when it has a source
file; external/module targets with no file stay `project:{name}`. Two functions
named `request` in different files are now two nodes.

### 2. Call resolution (the hard part)
The parser emits calls by name (`calls "request"`) with no idea *which* one.
Resolution runs at ingest, using the receiver type we already capture:

- Index every definition: `defs_by_name[name] -> [(node_id, file)]` and
  `class_file[ClassName] -> file`.
- For each call to `name` with `receiver_type = T`:
  1. if `class_file[T]` exists and a definition of `name` lives in that file →
     link to it (e.g. `self.send()` in a `Session` method → `send` in
     `sessions.py`).
  2. else if exactly one definition of `name` exists → link to it.
  3. else (ambiguous, no type) → link to a name-only bucket `project:{name}`
     so the edge is not lost. This is no worse than today's merge for that
     specific call; everything resolvable is now precise.

The *caller* side of any triple always resolves cleanly: a caller is defined in
the triple's `source_file`, so its id is `project:{source_file}:{name}`.

### 3. Query resolution
Lookups that took a bare/qualified name now resolve to node id(s):
`_resolve_query_nodes("Session.send")` → the `send` node in the file where
class `Session` is defined; `_resolve_query_nodes("send")` → all `send` nodes.
Updated in `find_callers`, `get_blast_radius`, `trace_flow`, `trace_calls`,
`find_styles`, and the flow edge-ordering helpers.

Node-iterating queries (`dead_code`, `grep`) are unaffected — they
never looked up by name.

## Class-level qualification (v2)

File-qualified ids still merge same-named methods of **different classes in the
same file** (e.g. click's `core.py` holds `Command`, `Context`, `Group`, each
with an `invoke`). Class qualification fixes this:

- Every triple carries `owner_class` — the class its `from_entity` is defined in
  (None for module-level). Method node ids become `project:{file}:{Class}.{name}`
  (node `name` attr stays the bare method for grep).
- Call resolution prefers a definition whose `owner_class == receiver_type`
  (`self.invoke()` in a `Command` method → `Command.invoke`), then falls back to
  same-file / single-candidate / name bucket.
- `_resolve_query_nodes("Command.invoke")` matches nodes with name `invoke` and
  owner `Command`.

## Scope / limits
- Precise for: single-definition names, and multi-definition names where the
  receiver type resolves (constructor / annotation / `self`/`this`).
- Falls back to the name bucket for genuinely ambiguous calls (multiple
  same-named methods, no receiver type) — same behavior as before for those.
- Requires a **re-ingest** (node ids change).
