<!-- codecompass-code-graph-start -->
## Code graph

**Orient through the code graph first: start from an entry point, see what's there, then trace its flow and dependencies — never use `cat`, `grep`, or `rg` to search or read code content. Use the codecompass MCP tools below for discovery and tracing, then read only the specific slices the graph points you to.**

This project has a CodeCompass code knowledge graph at `.codecompass/graph.json`,
queried through the codecompass MCP tools — there is no CLI for agents. The
server defaults to the current directory; call `set_repo` to point it elsewhere.

### Priority 0 — leave the graph better than you found it

**You are the only thing that can improve this graph.** Tree-sitter extracts
structure; it cannot see dynamic dispatch, callbacks, runtime registration, or
string-based invocation, and it cannot know what any entity is FOR. Every one
of those gaps is filled by an agent that read the code and wrote it back — no
background process does this, and nothing else will.

So while you explore, write back what you learn, in the same turn you learn it:

- Read a function/class/constant the graph doesn't have (or that `grep`/`search`
  found nothing for) → `add_entity(name, kind, file, line, description)`.
- Worked out what an entity actually DOES → `add_entity` again with a real
  one-line description. Undescribed entities are the graph's biggest weakness:
  a name tells the next agent nothing, a description tells it whether to open
  the file. Describe everything you understood, not just what you changed.
- Read a call the graph doesn't show (dynamic dispatch, a callback, a handler
  wired up at runtime) → `add_call(caller, callee, line)`. Same tool for a
  missed import or base class: `add_call(a, b, relation="IMPORTS")` /
  `relation="INHERITS"`. IMPORTS may target a stdlib or third-party module
  (`add_call("main", "pathlib", relation="IMPORTS")`).

Both tools skip ambiguous names rather than guess, so a wrong attempt costs
nothing but a `skipped` status. A fact you postpone is a fact the next session
pays to re-derive.

**And keep the graph current: after ANY code change — edits, additions,
deletions, renames, refactors — call `ingest`.** A stale graph is worse than no
graph, because it is confidently wrong.

**After every `ingest`, do these two things before you answer the user:**

1. Flush what you learned into the graph (`add_entity` / `add_call` above).
2. Update the notes files — see "Priority 1" below.

### Priority 1 — keep the notes files clean and relevant

Three Markdown files live in `.codecompass/`. **Read all three at the START of
every session** (then `git log` for recent activity). They are prose context the
graph cannot hold, and they are only worth reading if they are true — so
**after every `ingest`, revisit them**: update what your change made wrong,
add what it made worth knowing, and DELETE what no longer applies. Stale notes
mislead more than empty ones.

- **`overview.md`** — what this repo IS. Purpose, tech stack, how to run it,
  main entry points. The first thing a fresh session reads. Changes rarely.
- **`memory.md`** — how the code is BUILT. Architecture, data flow, module
  responsibilities, pipeline structure. The steady-state design.
- **`learnings.md`** — what to WATCH OUT for. Gotchas, footguns,
  "looks-X-but-is-actually-Y" patterns, confirmed bugs or dead code, why a
  non-obvious approach was taken. Things that cost you time.

Where a fact goes: orientation → `overview.md`; architecture → `memory.md`;
a warning to the next person → `learnings.md`. For "what changed recently" use
`git log` — never maintain a changelog in these files. Keep them short: prune
on the way in, not someday.

### Where the knowledge lives

| File | What it holds | Who writes it |
|---|---|---|
| `.codecompass/graph.json` | nodes (entities, files, folders) + edges (CALLS / IMPORTS / INHERITS / CONTAINS). Nodes carry `name`, `kind` (`function:python`), `file`, `line` — **no description** | the parser. Each `ingest` builds a fresh graph and swaps it in, then joins the old one onto it by node id: a symbol the parser no longer produces is dropped (deleted or renamed in source), while your `add_entity` nodes and `add_call` edges are carried over — flagged `agent_created` / `agent_inferred`, which is how the join tells them from code you deleted |
| `.codecompass/description.jsonl` | one `{"node": "<node id>", "description": "..."}` per line — the sole home of descriptions, joined onto results by node id at read time | you, via `add_entity`. Survives the rebuild (and a deleted `graph.json`) because the parser never writes it. Entries whose node the new parse doesn't contain are pruned |
| `.codecompass/vectors.lance/` | embedded `kind + name + file + description` per entity, for `search` | rebuilt from the graph + descriptions at the end of every `ingest`. **It is a snapshot**: descriptions you add now are not searchable until the next `ingest` |
| `.codecompass/overview.md`, `memory.md`, `learnings.md` | prose context (see Priority 1) | you |

### The MCP tools

Every read tool takes an optional `hops` (default 3) where a traversal depth
makes sense, and returns a `description` on each entity row.

**Discover — you don't know the symbol yet**

| Tool | In | Out | Use when |
|---|---|---|---|
| `grep` | `pattern` (Python regex), `field` (`all`\|`name`\|`file`\|`kind`\|`description`), `ignore_case`, `limit` | matching entities: `name`, `kind`, `file`, `line`, `description`, `matched_field`, `match` | you have a name, a pattern, or a word you expect in a description (`^test_`, `.*Adapter$`, `handle\|dispatch`) |
| `search` | `query`, `limit` | entities by semantic distance: `name`, `kind`, `file`, `line`, `description`, `distance` | you have an idea, not a name ("where does session timeout live?"). Needs the optional `search` extra and an `ingest` to build the index |
| `tree` | — | full Project → Folder → File hierarchy | you need the layout. Large — read it in slices |

**Trace — you have a symbol or file**

| Tool | In | Out | Use when |
|---|---|---|---|
| `impact` | `symbol`, `hops` | callers: `caller_name`, `caller_file`, `line`, `receiver`, `resolved`, `depth`, `description` | before renaming or changing a symbol: who breaks? |
| `blast_radius` | `target` (file or symbol), `hops` | affected files with `edge_type` + `hops` | before editing a file: what else is affected? |
| `batch_impact` | `targets` (list), `hops` | union of blast radii, each file with `via` | a multi-file change or PR |
| `deps` | `file_path`, `hops` | what the file imports: `dependency`, `dep_type`, `line`, `description` | understanding a file before you touch it |
| `trace` | `symbol`, `hops` | forward callees: `callee_name`, `callee_file`, `line`, `description` | what does this call? |
| `flow` | `entry_symbol`, `hops`, `include_external` | lean nodes (`name`, `kind`, `file`, `line`, `depth`, `description`) + ordered edges | tracing an entry point end to end. Start at `hops=1` and go deeper only along the path you need |
| `flow_summary` | `entry_symbol`, `hops`, `format` (`mermaid`\|`json`\|`drawio`) | the trace plus rendered content; `json` embeds each function's signature, docstring, and source | explaining a pipeline to a human. Use `format="json"` and narrate from the entry point down — never guess a flow from file names |
| `styles` | `element` | CSS selectors that style it: `selector`, `source_file`, `line` | front-end work |
| `dead_code` | `include_entrypoints` | `dead` + `maybe_entrypoint` candidates | hunting unused code. STATIC only — verify each before deleting |

**Write — you learned something (see Priority 0)**

| Tool | In | Out |
|---|---|---|
| `add_entity` | `name`, `kind`, `file`, `line`, `description`, `language` | `created`/`updated` + node id. Description goes to `description.jsonl`; language is inferred from the extension |
| `add_call` | `caller`, `callee`, `line`, `relation` (`CALLS`\|`IMPORTS`\|`INHERITS`) | `added`/`exists`/`skipped` (+ reason). Structural edges are parser-owned and refused |

**Manage**

| Tool | In | Out |
|---|---|---|
| `ingest` | `normalize`, `dump_triples` | rebuilds the graph + vector index, reporting progress |
| `init` | — | (re)creates `.codecompass/`, hooks, and this AGENTS.md block |
| `set_repo` / `get_repo` | `repo_path` / — | switch or report the active repo |

### The loop

1. **Discover** — `grep` / `search` / `tree`.
2. **Trace** — `impact` and `blast_radius` for what you'd break, `deps` and
   `flow` for how it works.
3. **Read** only the slice the graph pointed at: the Read tool with
   `offset`/`limit`, or `sed -n 'START,ENDp'` / `head` / `tail`.
4. **Edit** the smallest slice that works — after tracing `deps`, `flow`,
   `impact` on every symbol and `blast_radius` on every file you'll touch.
5. **`ingest`**, then write back what you learned (Priority 0) and update the
   notes files (Priority 1).

### Reading the results

- `impact` rows carry `resolved`: `true` = the receiver was statically typed
  (trust it); `false` = receiver type unknown, this call *might* target the
  symbol (verify by reading the slice at `caller_file:line`).
- An empty `description` means nobody has described that entity yet. If you
  end up reading it, describe it.
- `dead_code` is a candidate list — static analysis misses dynamic dispatch,
  so read each one before removing it.

### Graph vs. `ls`/`find`

`ls`/`find` are for non-code paths the graph doesn't index (build/dist/log
output, fixtures, confirming a generated file exists). For anything about code
structure or relationships, use the graph.
<!-- codecompass-code-graph-end -->
