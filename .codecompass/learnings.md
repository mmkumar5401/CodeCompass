# Learnings

Engineering decisions, bugs, and insights for the CodeCompass tool itself.

## Parser call-resolution bugs (fixed) — graph completeness depended on these

The call graph was silently lossy. Two bugs in `ingestion/code_parser.py` dropped
or misattributed a large fraction of CALLS edges. Both surfaced only when building
dead-code analysis, because false "dead" results exposed the missing edges.

### Bug 1: private-helper calls were dropped
`_is_meaningful_callee()` filtered out any callee whose name started with `_`.
This discarded every call to a single-underscore private helper (e.g.
`_build_content_ids`, `_parse_terms`) — exactly the calls a call graph needs.
**Fix:** filter only dunders (`name.startswith("__")`), not single underscores.
**Impact on goal-tagger:** +288 triples recovered (1621 → 1909).
**Why it mattered:** without this, ~half of all functions looked like dead code.

### Bug 2: `obj.method()` resolved to the object, not the method
`_extract_python_callee()` handled `attribute` nodes by returning the FIRST
`identifier` child via `_child_of_type`. For `pipeline.submit_reasoner(...)` the
first identifier is `pipeline` (the object), so the edge pointed at a bogus
`pipeline` node and the real `submit_reasoner` looked uncalled. It also created
junk nodes for object names (`pd`, `df`, `pipeline`).
**Fix:** for an `attribute` node, take the LAST identifier — the attribute being
called — via `child_by_field_name("attribute")`, falling back to the last
`identifier` child.
**Impact on goal-tagger:** removed ~114 bogus nodes (546 → 432), eliminated the
biggest source of false-positive dead code (submit_*/retrieve_* pipeline fns).

**Consequence:** these fixes change call resolution for EVERY repo. Any graph
built before them is stale and should be re-ingested. Dead-code precision on
goal-tagger went 143 → 54 → 5 candidates as each bug was fixed.

## Dead-code analysis design

`codecompass query --dead-code` → `find_dead_code()` in `code_graph_client.py`.
- Dead = Entity node with no inbound CALLS/IMPORTS/REFERENCES/INHERITS edge,
  scoped to the project, with a non-empty `file` attr (skip external/stdlib).
- Classify into `dead` (true suspects) vs `maybe_entrypoint` via
  `_looks_like_entry_point()`: modules are never "dead"; names matching
  `run_/main/handle_/cmd_/test_/setup_/teardown_` prefixes or
  `{main,handler,lambda_handler,application,app}` are runtime-invoked, not
  statically called.
- **Key principle: candidate report, NOT a verdict.** Static analysis can't see
  dynamic dispatch, reflection, or string-based invocation. Output always tells
  the user to grep-verify before deleting. Hide entry points by default
  (`--include-entrypoints` to show) so the signal isn't drowned by CLI dispatch.

## Flow narration design (`--flow --format json`)

Decision: do NOT thread signature/docstring through CodeTriple or store source in
the graph (keeps graph lean). Instead extract per-entity context ON DEMAND at flow
time by re-reading source files with tree-sitter.
- `ingestion/source_context.py::extract_entity_context(repo_root, rel_file, name)`
  returns `{signature, docstring, snippet, start_line, end_line}`. Reuses parser
  internals (`_PARSER_LOADERS`, `_child_of_type`, `_text`, `_walk`). Python +
  JS/TS. Snippet capped at 1200 chars. Never raises — empty fields on failure.
- `--flow --format {drawio,mermaid,json}`. `_order_edges()` numbers calls
  per-parent by source line (the `order` field = call sequence). JSON payload is
  built for an agent to narrate real data flow (signatures + docstrings describe
  data in/out, snippet explains the transformation).

## Mermaid gotchas (from prior session, still true)
- `call` is a reserved Mermaid keyword (parses as CALLBACKNAME) — use class names
  `fn`/`leafFn`/`stepNode`/`entryNode`, never `call`/`leaf`/`step`.
- Auto-layout (Mermaid) beats hand-positioned draw.io for fan-outs.
- draw.io drops any edge lacking `<mxGeometry relative="1" as="geometry"/>`.

## AGENTS.md regeneration
`init` and `ingest-code` both call `_register_project_agents_md()`, which replaces
only the marked block (`<!-- codecompass-code-graph-start -->` … end) — user
content outside the markers is preserved. Re-ingesting is how the managed block
picks up template changes in `main.py`.
