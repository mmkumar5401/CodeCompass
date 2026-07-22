<!-- codecompass-code-graph-start -->
## Code graph

**Orient through the code graph first: start from an entry point, see what's there, then trace its flow and dependencies — never use `cat`, `grep`, or `rg` to search or read code content. Use the codecompass MCP tools below for discovery and tracing, then read only the specific slices the graph points you to.**

This project has a CodeCompass code knowledge graph at `.codecompass/graph.json`.
Every node carries `kind` (e.g. `function:python`, `class:typescript`) and a
human-readable `description`. Use it as your primary navigation tool.

The graph is queried through the codecompass MCP tools — there is no CLI for
agents. The server defaults to the current directory; call `set_repo` to point
it at another repo.

### The loop: discover → trace → read → edit

1. **Discover** — find the symbol(s) you care about (pick by what you have):

   | You have… | Use | Example |
   |---|---|---|
   | a concept, name, or pattern | `grep` | `grep(pattern="^Session")`, `grep(pattern=".*Adapter$")` |
   | an idea, not a name ("where does caching go?") | `search` | `search(query="session timeout")` — semantic vector search over entity names/kinds/files/descriptions (needs the optional `search` extra + an ingest to build the index) |
   | the full layout | `tree` | (large — read it in slices) |

2. **Trace** — understand relationships around a known symbol/file:

   | Question | Use |
   |---|---|
   | who calls / would break if I change this symbol? | `impact` |
   | what files are affected if I edit this file? | `blast_radius` |
   | what does this file depend on? | `deps` |
   | what does this entry point call, step by step? | `flow` (lean structure) |
   | explain a flow to a human (diagram + narration) | `flow_summary` |
   | is anything unused? | `dead_code` |

3. **Read** the specific slice the graph pointed you to (Read tool / `sed -n`),
   not the whole file.

   Use the Read tool with `offset` and `limit`, or shell snippets like
   `sed -n 'START,ENDp'`, `head`, and `tail`, to pull only the function or
   slice the graph identified. For edits, use the edit tool with exact matched
   text; rewrite the smallest slice that works, not the whole file.

4. **Edit** — before editing, verify the target fully so you don't break callers or dependents:
   - Run `deps` to understand what the file relies on.
   - Run `flow` (or `flow_summary`) to trace the logic end-to-end.
   - Run `impact` for every symbol you plan to change.
   - Run `blast_radius` for every file you plan to change.
   - Read the specific slices the graph identified.
   - Then make the smallest correct change.

   After any code change (edits, additions, deletions, renames, refactors), re-ingest so the graph stays current:
   call the `ingest` tool.

### Reading the results

- `impact` rows carry `resolved`: `true` = the receiver was statically typed
  (trust it); `false` = receiver type unknown, this call *might* target the
  symbol (verify by reading the slice at `caller_file:line`).
- `flow` is lean (structure only). Start at `hops=1` and only go deeper along
  the one path you actually need — deep hops on a high-fan-out symbol are large.
- `dead_code` is a candidate list — static analysis misses dynamic dispatch,
  so read each before removing.

### Graph vs. `ls`/`find`

`ls`/`find` are for non-code paths the graph doesn't index (build/dist/log
output, fixtures, confirming a generated file exists). For anything about code
structure or relationships, use the graph.

### Explaining how something works

When asked to explain a pipeline, feature, or "what happens when X", do NOT
guess from file names. Trace it with the `flow_summary` tool (`format="json"`).

The JSON gives you, for every function in the flow: its real signature,
docstring, source snippet, and the ordered call sites (the `order` field on
each edge is the call sequence by source line). Narrate the data flow from the
entry point downward — describe what data enters and leaves each function using
the signatures and docstrings, and explain the transformations from the source
snippets. For just the call structure without the embedded source, use `flow`.

### Finding dead code

The `dead_code` tool lists entities with no inbound caller or
importer — candidates for removal (old helpers, superseded versions, orphaned
scripts). Results are split into "likely dead" and (with
`include_entrypoints=True`) "possible entry points".

This is STATIC analysis: dynamic dispatch, reflection, and string-based
invocation are invisible. Treat every result as a candidate — use the `grep`
tool to confirm it is truly
unused before deleting it.

### Project notes: `overview.md`, `memory.md`, `learnings.md`

Three files live in `.codecompass/`. **At the START of every session, read all
three** (then `git log` for recent activity) to get full context. Write to them
as you learn things worth keeping. They serve DISTINCT purposes — do not mix them
up:

- **`overview.md`** — what this repo IS. Purpose, tech stack, how to run it, main
  entry points. The first thing a fresh session should read. Answers "what am I
  looking at?" Changes rarely.

- **`memory.md`** — how the code is BUILT. Architecture, data flow, module
  responsibilities, pipeline structure. Answers "how does this project work?"
  Save a fact here when it describes the steady-state design.

- **`learnings.md`** — what to WATCH OUT for. Non-obvious gotchas, footguns,
  "looks-X-but-is-actually-Y" patterns, confirmed bugs or dead code, and the
  reasons behind non-obvious decisions. Answers "what surprised me / what cost me
  time?" Save a fact here when a future agent would otherwise repeat your mistake.

For "what changed recently", use `git log` — do NOT maintain a changelog in these
files. Quick test for where a fact goes: orientation → `overview.md`; architecture
doc → `memory.md`; code-comment warning to the next person → `learnings.md`.

### When to re-ingest

- AFTER every ingest: always flush what you learned while reading code —
  record missed entities with `add_entity` (fill every field: kind, file, line,
  one-line description; language is inferred from the file) and missed calls
  with `add_call`. Agent-recorded data survives the rebuild.
- After every code change: edits, additions, deletions, renames, refactors —
  call the `ingest` tool
- After major refactors (moved functions, renamed classes)
- If query results look stale or incomplete

### The graph improves with use — record what it missed (NOT optional)

Exploring the code is how you find what the parser missed, so write it back as
you go — every session, not only when asked:

- Read a function/class/constant the graph doesn't have (or `grep`/`search`
  found nothing for) → `add_entity(name, kind, file, line, description)`.
- Read a call the graph doesn't show — dynamic dispatch, a callback, a handler
  wired up at runtime → `add_call(caller, callee, line)`. Same tool for a
  missed import or base class: `add_call(a, b, relation="IMPORTS")` /
  `relation="INHERITS"`. IMPORTS targets may be stdlib or third-party
  modules (`add_call("main", "pathlib", relation="IMPORTS")`).
- Worked out what an entity actually does → `add_entity` again with the real
  one-line description; it overwrites the placeholder.

Record it in the same turn you learned it, before you answer the user — a fact
you postpone is a fact the next session re-derives. Both tools mark entries
`agent_inferred` and skip anything ambiguous rather than guess, so a wrong
guess costs nothing but a `skipped` status. Small opportunistic writes keep
the graph accurate between full `enrich` runs.

### Enrichment — user-triggered ONLY

The `enrich` tool stages entities for an agent swarm to fill in one-line
descriptions and missing call edges (see `.codecompass/enrich/INSTRUCTIONS.md`
when staged; merge with `enrich(apply=True)`). This is expensive and
**must only run when the user explicitly asks** for enrichment (e.g. "enrich
the graph", "add descriptions", "fill in missing calls").

**Do NOT run `enrich` automatically** after re-ingesting, editing files, or
any other routine step — routine re-ingestion is the `ingest` tool.
<!-- codecompass-code-graph-end -->
