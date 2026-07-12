<!-- This file must stay byte-for-byte identical to its counterpart in pi-package/templates/. Run scripts/check-pi-package-sync.sh to verify. -->
## Code graph

**Read `.codecompass` before making any changes or before reading any file. If you think codecompass will help in any way, use it.**

This project has a CodeCompass code knowledge graph at `.codecompass/graph.json`.
Every node carries `kind` (e.g. `function:python`, `class:typescript`) and a
human-readable `description`. Use it as your primary navigation tool.

All commands default to the current directory — run them from the project root.

### Rules — MUST follow

0. **Never use `cat`, `grep`, or `rg` to search or read code content.**
   Use the `codecompass query` commands below to find entities, structure, and
   relationships instead — they know the real dependency graph; grepping does
   not. Only `read` a specific file once codecompass has told you it matters.
   `ls`/`find` are fine for non-code exploration — see the decision rule below.
1. **Before editing any file or symbol**, verify it through the graph so you
   don't miss callers, dependencies, or logic:
   - Run `--deps <file>` to see what the file relies on.
   - Run `--flow <entry_symbol> --format json` to trace the logic end-to-end.
   - Run `--impact <symbol>` for every symbol you plan to change.
   - Run `--blast-radius <file>` for every file you plan to change.
   - Read only the specific slices the graph identified.
   - Then make the smallest correct change.
2. **After any code change** (edits, additions, deletions, renames, refactors),
   re-ingest so the graph stays current:
   ```bash
   codecompass ingest-code
   ```
3. **Never skip step 1.** Reading or editing without checking blast radius,
   impact, flow, and dependencies first means you may break callers, importers,
   or logic you didn't see.

### Graph vs. `ls`/`find` — how to decide

Use **codecompass** when the question is about code structure or relationships:
"what calls this", "what depends on this file", "what does this module do",
"how does this flow work", "is this dead code". The graph knows the real
dependency edges; a directory listing does not.

Use **`ls`/`find`** when the question has nothing to do with code
relationships: confirming a generated/output file exists, listing a
build/dist/log directory, checking test fixtures or assets, or any path the
graph doesn't index. These are fine — don't force codecompass onto questions it
can't answer.

### Available queries

| Command | Purpose |
|---|---|
| `codecompass query --blast-radius <file_or_symbol>` | All nodes affected if you change this |
| `codecompass query --impact <symbol>` | Downstream callers / importers of a symbol |
| `codecompass query --deps <file>` | What this file depends on |
| `codecompass query --tree` | Full project structure with entity types |
| `codecompass query --dead-code` | Find functions/classes with no caller or importer (candidates to remove) |
| `codecompass query --flow <entry_symbol>` | Trace a call/import flow from an entry point (draw.io diagram by default) |
| `codecompass query --flow <entry_symbol> --format mermaid` | Same trace as a Markdown mermaid flowchart (renders on GitHub) |
| `codecompass query --flow <entry_symbol> --format json` | Same trace enriched with signatures, docstrings, and source snippets |

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
