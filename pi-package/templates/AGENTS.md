<!-- codecompass-code-graph-start -->
<!-- This file must stay byte-for-byte identical to its counterpart in pi-package/templates/. Run scripts/check-pi-package-sync.sh to verify. -->
## Code graph

**Orient through the code graph first: start from an entry point, see what's there, then trace its flow and dependencies — never use `cat`, `grep`, or `rg` to search or read code content. Use the `codecompass query` commands below for discovery and tracing, then read only the specific slices the graph points you to.**

This project has a CodeCompass code knowledge graph at `.codecompass/graph.json`.
Every node carries `kind` (e.g. `function:python`, `class:typescript`) and a
human-readable `description`. Use it as your primary navigation tool.

All commands default to the current directory — run them from the project root.

### The loop: discover → trace → read → edit

1. **Discover** — find the symbol(s) you care about (pick by what you have):

   | You have… | Use | Example |
   |---|---|---|
   | a feature request that names a concept ("session timeout", "adapter retries") | `--grep <concept>` first | `--grep "^Session"` — scope straight to it (cheap); only fall back to `--map` if the concept isn't a symbol name |
   | a regex / name pattern | `--grep <regex>` | `--grep "^get_"`, `--grep ".*Adapter$"` |
   | keywords | `--search <words>` | `--search "session cookie"` |
   | a truly nameless need ("where does caching go?" with no `cache` symbol) | `--map` | read the compact index and reason about where it belongs |
   | the full layout | `--tree` | (large — prefer `--map` for reasoning) |

2. **Trace** — understand relationships around a known symbol/file:

   | Question | Use |
   |---|---|
   | who calls / would break if I change this symbol? | `--impact <symbol>` |
   | what files are affected if I edit this file? | `--blast-radius <file>` |
   | what does this file depend on? | `--deps <file>` |
   | what does this entry point call, step by step? | `--flow <symbol>` (lean structure) |
   | explain a flow to a human (diagram + narration) | `--flow-summary <symbol>` |
   | is anything unused? | `--dead-code` |

3. **Read** the specific slice the graph pointed you to (Read tool / `sed -n`),
   not the whole file.

4. **Edit** — before editing, verify the target fully so you don't break callers or dependents:
   - Run `--deps <file>` to understand what the file relies on.
   - Run `--flow <entry_symbol> --format json` (or `--flow-summary <entry_symbol>`) to trace the logic end-to-end.
   - Run `--impact <symbol>` for every symbol you plan to change.
   - Run `--blast-radius <file>` for every file you plan to change.
   - Read the specific slices the graph identified.
   - Then make the smallest correct change.

   After any code change (edits, additions, deletions, renames, refactors), re-ingest so the graph stays current:
   ```bash
   codecompass ingest-code
   ```

### Reading the results

- `--impact` rows carry `resolved`: `true` = the receiver was statically typed
  (trust it); `false` = receiver type unknown, this call *might* target the
  symbol (verify by reading the slice at `caller_file:line`).
- `--flow` is lean (structure only). Start at `hops=1` and only go deeper along
  the one path you actually need — deep hops on a high-fan-out symbol are large.
- `--dead-code` is a candidate list — static analysis misses dynamic dispatch,
  so read each before removing.

### Graph vs. `ls`/`find`

`ls`/`find` are for non-code paths the graph doesn't index (build/dist/log
output, fixtures, confirming a generated file exists). For anything about code
structure or relationships, use the graph.

### Explaining how something works

When asked to explain a pipeline, feature, or "what happens when X", do NOT
guess from file names. Trace it:

```bash
codecompass query --flow <entry_symbol> --format json
```

The JSON (written to `.codecompass/flow_<entry>.json`) gives you, for every
function in the flow: its real signature, docstring, source snippet, and the
ordered call sites (the `order` field on each edge is the call sequence by
source line). Narrate the data flow from the entry point downward — describe
what data enters and leaves each function using the signatures and docstrings,
and explain the transformations from the source snippets.

### Finding dead code

`codecompass query --dead-code` lists entities with no inbound caller or
importer — candidates for removal (old helpers, superseded versions, orphaned
scripts). Results are split into "likely dead" and (with `--include-entrypoints`)
"possible entry points".

This is STATIC analysis: dynamic dispatch, reflection, and string-based
invocation are invisible. Treat every result as a candidate — use
`codecompass query --grep <name>` or `--search <name>` to confirm it is truly
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

- After every code change: edits, additions, deletions, renames, refactors
- After major refactors (moved functions, renamed classes)
- If query results look stale or incomplete

### Description enrichment — user-triggered ONLY

`codecompass describe` (and `ingest-code --describe`) stage entity descriptions
for an agent swarm to fill in (see `.codecompass/describe/INSTRUCTIONS.md` when
staged). This is expensive and **must only run when the user explicitly asks**
for descriptions to be added or refreshed (e.g. "describe this codebase",
"add descriptions", "enrich the graph").

**Do NOT run `describe` automatically** after re-ingesting, editing files, or
any other routine step — routine re-ingestion is `codecompass ingest-code`
with no `--describe` flag.
<!-- codecompass-code-graph-end -->
