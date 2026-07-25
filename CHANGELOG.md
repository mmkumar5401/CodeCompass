# Changelog

## [7.1.1] - 2026-07-25

### Fixed
- **The guard never ran in opencode.** init registered a plugin named
  `opencode-hooks-api` — the title of the project's GitHub repo and README, but
  not what it publishes as. The npm package is `opencode-hooks-plugin`, so
  opencode resolved nothing and the hooks in `.claude/settings.json` were never
  fired. Existing configs carrying the dead name are rewritten in place.
- **The hook command now resolves the project root on every host.** Each bridge
  announces it differently: Claude Code sets `$CLAUDE_PROJECT_DIR`,
  `opencode-hooks-plugin` sets `$OPENCODE_PROJECT_DIR` and spawns with no cwd of
  its own, and `@hsingjui/pi-hooks` sets no variable but does spawn at the
  project root. The command falls through all three. This failed silently
  before: the script wasn't found, bash exited non-2, and both bridges treat a
  non-2 exit as a non-blocking error rather than a denial.
- `install.sh` drops the package's uv cache entries before installing.
  `--refresh` alone could still resolve to the previous version, or fail with
  "no version of codecompass-mcp==\<new\>", immediately after a release.

### Changed
- **No more repo-level `opencode.json`.** Registering the plugin belongs in the
  user-global config, which `setup_opencode` writes and which applies to every
  repo; the project copy only ever added a file to your tree. init now removes
  the one older versions created, keeping the file if you had put anything of
  your own in it and leaving an unparseable one untouched.

## [7.1.0] - 2026-07-25

### Changed
- **The guard hook now blocks by index, not by repo.** `grep`/`glob`/`cat` are
  denied only where the graph has an answer: an indexed file, or a directory
  containing one. Only parsed languages become File nodes, so a repo's
  yaml/md/json/lock files now pass through — blocking them cost a turn and
  offered no alternative, since no graph query describes a file the parser
  never read. On a sample repo this was 37% of tracked files.
- A directory is judged by what it contains, so `grep -r foo src/` is blocked
  while `grep -r foo docs/` is allowed. A file is its own scope, which keeps
  one rule covering both the search tools and whole-file dumps.

### Added
- **`.codecompass/files.txt`** — every indexed path, one per line, written by
  ingest right after the graph swap. The hook reads this instead of
  `graph.json`: it runs on every Bash/Grep/Glob call, and a few KB of paths
  answers the containment question without parsing a multi-megabyte graph.
  Added to the generated `.gitignore` alongside the other rebuilt artifacts.
- `init` backfills `files.txt` from an existing graph, so repos ingested by an
  earlier version keep their guard instead of silently allowing everything
  until their next ingest.

### Fixed
- The guard's path comparison is now case-insensitive on both sides of the
  relative-path calculation. `os.path.realpath` doesn't canonicalize case, so
  a host passing a differently-cased cwd produced `../repo/a.py` and matched
  nothing in the index — the guard would have switched off silently.

## [7.0.3] - 2026-07-25

### Changed
- **Root AGENTS.md is no longer written.** The code exploration requirements
  checklist moved into the per-host instruction files (`.claude/CLAUDE.md`,
  `.pi/SYSTEM.md`, `.opencode/AGENTS.md`); init strips the managed block from
  the root AGENTS.md (deleting the file when the block was all it held,
  preserving user content otherwise).

## [7.0.2] - 2026-07-25

### Changed
- **Vector index builds by default on ingest** (`skip_vectors` now defaults to
  False, CLI and MCP alike). Without the `[search]` extra Phase 5 still skips
  quietly.

## [7.0.1] - 2026-07-25

### Fixed
- **`opencode_setup` was missing from the wheel** — `py-modules` didn't list
  it, so a pip/uv-installed `codecompass setup` crashed with
  ModuleNotFoundError.

## [7.0.0] - 2026-07-25

### Changed
- **`init` is now multi-host.** Generated knowledge lives once in `.agents/`
  (`codecompass.md` — the canonical instruction block, and
  `hooks/block-file-search.py` — one guard script); each host gets a thin
  pointer at its native location: `.claude/CLAUDE.md`, `.pi/SYSTEM.md`,
  `.opencode/AGENTS.md`, plus the managed block (with the code exploration
  requirements checklist) in the root `AGENTS.md`. The same guard script
  serves Claude Code (`.claude/settings.json`, exit 2), pi (pi-hooks extension
  + `.pi/settings.json`, deny JSON) and opencode (opencode-hooks-api plugin
  reading the same `.claude/settings.json`). `setup-pi` now also installs
  `@hsingjui/pi-hooks`; new `codecompass setup-opencode` / `codecompass setup`
  wire opencode's global config. Stale repos auto-heal on first MCP use,
  keyed off `.agents/codecompass.md`; pre-7.0 generated files (root
  `claude.md`, `.pi/agent/AGENTS.md`, `.pi/extensions/codecompass-guard.ts`,
  `.claude/hooks/`) are migrated away automatically.
- **Descriptions are node attributes again.** `description.jsonl` is gone:
  the ingest join already carries node attributes across a rebuild, so the
  sidecar was a second source of truth for nothing. Pre-7.0 sidecars are
  adopted onto their nodes on first load, then deleted.
- **Vector search engine: LanceDB → turbovec.** The `[search]` extra is now
  `turbovec` + `fastembed` (no pyarrow, no database — a Rust TurboQuant index
  at `.codecompass/vectors.tvim` plus a JSON payload sidecar). Same lifecycle:
  wiped and rebuilt at the end of every ingest.
- **`install.sh` rewritten** as a curl-able, uv-only installer: bootstraps uv
  (which brings its own managed Python — no system Python or project venv
  needed), `uv tool install codecompass-mcp`, then `codecompass setup` wires
  every agent host present. All hosts are pointed at the uv binary
  (`~/.local/bin/codecompass-mcp`) — `_server_command` prefers it over
  PATH/venv resolution, so reinstalling into a different environment can't
  strand an agent on a stale interpreter.

### Added
- **`delete_entity` / `delete_call`** — the undo for `add_entity` / `add_call`,
  as MCP tools and `ingestion.agent_writes` functions. `delete_entity` removes
  an agent-created node outright (edges and description with it); for a
  parser-produced node it strips only the agent's additions (description,
  agent_inferred edges/flags), since the node itself would be re-parsed on
  ingest anyway. `delete_call` removes only agent_inferred edges — parser
  edges are parser-owned.
- **`modify_relation`** — retype an existing edge, including a parser edge the
  parser got wrong (`CALLS` → `INHERITS`, etc.). The retyped edge is marked
  `agent_relation=True`; on the next ingest join the agent's relation wins for
  that node pair — the freshly parsed edge of the old type is dropped and the
  agent's relation restored. MCP tool + `ingestion.agent_writes` function.
- **Free-form relations.** `add_call`/`delete_call`/`modify_relation` no longer
  restrict `relation` to CALLS/IMPORTS/INHERITS — the agent names what the
  code actually does (`DISPATCHES`, `LISTENS_TO`, …), normalized to
  UPPER_SNAKE. Only the parser-owned structural relations CONTAINS/DEFINED_IN
  are refused.
- **First-class ambiguity handling on all four write tools.** A shared name
  used to mean a flat `skipped`; it now returns `ambiguous` with the candidate
  list (`id` + `file`), and `add_call`/`delete_call` take `caller_file` /
  `callee_file` (plus an exact `id` target on `delete_entity`) so the agent
  can aim at exactly one. `add_entity` no longer silently updates the first
  of several same-named entities.

### Removed
- The pi guard extension (superseded by pi-hooks), the LanceDB dependency,
  and `description.jsonl` (see above).

### Fixed
- **Guard silently allowed everything when cwd case differed from the
  registry** (macOS/Windows): repo matching is now case-insensitive.
- **Tests no longer pollute the real `~/.codecompass/repos` registry.**

## [6.2.0] - 2026-07-22

### Added
- **`.ccignore` — per-repo exclusions.** Until now the only way to keep a
  directory out of the graph was to be one of the fourteen hardcoded names
  (`node_modules`, `dist`, `.venv`, …). Anything else got indexed: a mid-size
  PHP repo spent 72k of its 96k entities on `vendor/`, inflating `graph.json`
  to 258 MB and making every `ingest` re-embed ~96k strings — around twelve
  minutes on a laptop CPU, nearly all of it Composer packages nobody will ever
  query. A `.ccignore` at the repo root now takes gitignore-style globs, one
  per line, `#` for comments. A pattern without a `/` matches any path
  component (`vendor` kills every `vendor` directory at any depth); one with a
  `/` is root-relative. No `!` negation. Honored by `ingest` and `watch` alike.

### Fixed
- **`watch` re-indexed files `ingest` had skipped.** The file watcher applied
  no skip rules at all, so a `composer install` or `npm ci` under a directory
  the parser deliberately ignored streamed straight back into the graph. It now
  shares the ingest ignore rules.

### Changed
- The two copies of the skip-directory list (`code_parser`,
  `hierarchy_builder`) are now one, in `ingestion/ignore.py`.

## [6.1.0] - 2026-07-22

### Changed
- **A project set up by an older codecompass now heals itself.** `init` only
  ran when `.codecompass/` was missing, so a repo initialized once — years ago,
  by any version — kept that directory forever and never received any generated
  file a later release added: guard hooks, the `.pi/` extension, the current
  AGENTS.md block. Queries kept working, so nothing looked broken. The server
  now also re-runs `init` when AGENTS.md doesn't carry this version's block, and
  `_register_project_agents_md` skips the write when the content is unchanged,
  so up-to-date repos pay nothing.

### Fixed
- **The pi server entry went into a file pi doesn't read.** `setup_pi` wrote
  only `~/.config/mcp/mcp.json`, which is the standalone `pi-mcp-adapter`'s
  config; pi reads `~/.pi/agent/mcp.json` natively. Both are now updated (the
  adapter's only if it already exists), and the merge touches just the
  `command` key — other servers, and options like `directTools` on the
  codecompass entry, are preserved. Invalid JSON is left alone rather than
  overwritten.

## [6.0.3] - 2026-07-22

### Fixed
- **`init` run from pi wrote no `.pi/` files.** Both the guard extension
  (`.pi/extensions/codecompass-guard.ts`) and `.pi/agent/AGENTS.md` were gated
  on `shutil.which("pi")` — but pi doesn't pass its own bin directory to the
  MCP server it spawns (node lives under nvm), so pi looked uninstalled inside
  the very process it asked to run `init`, and the repo silently got neither
  file. The same blind spot skipped skill/mcp.json setup in `pi_setup`.
  Detection now falls back to `~/.pi`, which is there regardless of `PATH`;
  machines without pi still get no `.pi/` directory.

## [6.0.2] - 2026-07-22

### Fixed
- **pi rejected the skill file with "description is required".** The
  generated-by marker added in 6.0.0 was written above the YAML frontmatter, so
  the opening `---` was no longer line 1 and pi parsed no frontmatter at all.
  The marker now sits in the body, directly after the closing delimiter, where
  it still drives the self-update check.

## [6.0.1] - 2026-07-22

### Fixed
- **pi could not spawn the MCP server.** `mcp.json` recorded the bare name
  `codecompass-mcp`, which resolves through `PATH` — and under pyenv that name
  is a shim that picks its Python from the launch directory's
  `.python-version`. Started outside the indexed project, pi resolved a Python
  without codecompass installed and silently got "command not found", while the
  same name worked in a shell inside the project. The entry now records the
  console script next to `sys.executable`, an absolute path immune to `PATH`
  and pyenv state, and `setup_pi` reconciles it on every run so reinstalling
  into a different environment self-corrects.
- **Skill files installed before 6.0.0 were never updated.** The new
  marker-based rewrite treated a markerless file as user-authored, which
  pinned every existing install to its original skill text — including the
  removed `enrich` tool. Copies carrying a known pre-marker signature are now
  adopted and refreshed; genuinely user-written files are still left alone.

## [6.0.0] - 2026-07-22

### Removed
- **The `enrich` tool and its CLI command are gone**, along with batch staging,
  `.codecompass/enrich/`, and `apply_enrich_results`. Descriptions and
  parser-invisible edges now come from one place: an agent writing what it
  learned with `add_entity`/`add_call` as it reads. `ingestion/enricher.py` is
  now `ingestion/agent_writes.py`, holding just those two tools.

### Changed
- **Ingest builds into `graph.json.copy` and swaps it in.** The rebuild no
  longer clears the live graph in place, so an ingest that crashes or is killed
  mid-parse leaves the previous graph fully intact; the swap itself is an
  `os.replace`, so a concurrent reader sees the old graph or the new one, never
  a truncated file. Once the new graph exists the old one is joined onto it by
  node id: surviving nodes keep attributes the parser didn't set, `add_entity`
  nodes and `add_call` edges are carried over, and anything the parser no
  longer produces is dropped. The description sidecar is written once, at that
  join, instead of on every intermediate save.
- **Descriptions live in `.codecompass/description.jsonl`, not on the graph
  nodes.** One `{"node": "<id>", "description": "..."}` per line, joined onto
  every result by node id. `graph.json` is parser output and is rebuilt
  wholesale each ingest; keeping descriptions out of it means they survive that
  rebuild — and a deleted `graph.json` — with no carry-over logic. Entries whose
  node the parser no longer produces are pruned at the end of each ingest.
  Graphs from older versions are migrated on first load: agent-authored
  descriptions move to the sidecar, generated placeholders are dropped.
- **No more placeholder descriptions.** An entity nobody has described reads as
  `""` instead of `"python function in x.py"` — real signal or nothing.
- **AGENTS.md rewritten around two standing priorities**: improving the graph
  (write back what you learn, re-ingest after every change) and keeping
  `overview.md` / `memory.md` / `learnings.md` correct after every ingest. It
  now documents every MCP tool with its inputs, outputs, and when to use it,
  plus what each file in `.codecompass/` holds and who writes it.
- **The pi skill file self-updates.** `setup_pi` rewrites a marker-bearing
  `SKILL.md` it previously installed when the package ships new text, instead of
  skipping forever once the file exists. A copy the user edited (marker removed)
  is still left alone.
- **Reworded the `next` write-back reminder** on every read result and on
  `ingest`: it now invites the agent to add whatever would make the graph more
  helpful, and after an ingest also to refresh the notes files.

### Fixed
- **`add_entity` no longer resurrects deleted symbols.** Describing a node the
  parser already produces marked it `agent_created`, which re-added it on every
  subsequent ingest even after the symbol was deleted from source. The flags
  (`agent_inferred` / `agent_created`, still what tells the join your work from
  code you deleted) are now set only for nodes `add_entity` actually creates.

## [5.3.0] - 2026-07-22

### Added
- **Every entity row carries its `description`.** `grep`, `impact`, `deps`,
  `trace`, `styles`, `dead_code`, and `flow` now return the graph's description
  alongside name/kind/file/line, so an agent can judge relevance without a
  follow-up read. `grep` already *matched* against descriptions; it now shows
  the one it matched. Descriptions stay generic until `enrich` fills them in.

## [5.2.0] - 2026-07-22

### Added
- **`ingest` streams progress.** The MCP tool now runs the blocking ingest in a
  worker thread and reports 0-100% progress notifications as it works
  (hierarchy → per-file parsing → normalize → graph write → vector index).
  `ingest_code(..., on_progress=)` and `parse_directory(..., on_progress=)`
  expose the same callback to non-console callers; the CLI progress bar is
  unchanged.
- **`add_call(..., relation=)`** records `IMPORTS` and `INHERITS` edges, not
  just `CALLS`. Structural edges (`CONTAINS`/`DEFINED_IN`) stay parser-owned
  and are refused. `IMPORTS` may target a stdlib or third-party module — the
  file-less module node is created when the graph has never seen it, and
  survives re-ingest. Ambiguous names are still skipped, never guessed.

### Changed
- **Guard hooks block git's own search and dump commands** — `git grep`,
  `git ls-files`, `git cat-file`, and `git log -S/-G` (Claude hook and pi
  extension). `git log`, `status`, `show`, and `diff` stay allowed.
- **Every graph read result carries a `next` reminder** to record missed
  entities and calls with `add_entity`/`add_call`, and the AGENTS.md template
  makes that write-back a standing rule rather than an option.

## [5.1.0] - 2026-07-21

### Added
- **Semantic vector search over entities** — new `search` MCP tool backed by
  `.codecompass/vectors.lance` (LanceDB + fastembed), rebuilt on every ingest.
  Optional: `pip install 'codecompass-mcp[search]'`.

## [5.0.0] - 2026-07-22

### Removed
- **BREAKING: the agent-facing CLI is gone — agents use MCP only.** Removed the
  `codecompass query`, `init`, `ingest-code`, `add-entity`, and `add-call`
  subcommands. Query/index/write operations are MCP tools (`grep`, `impact`,
  `blast_radius`, `deps`, `flow`, `flow_summary`, `dead_code`, `tree`, `init`,
  `ingest`, `enrich`, `add_entity`, `add_call`, `set_repo`). The CLI keeps only
  operational commands: `enrich`, `load-triples`, `watch`, `mcp`, `setup-pi`.
  `graph/code_query_cli.py` is now `graph/code_queries.py` (fetch helpers only).

### Added
- **`ingest` MCP tool accepts `normalize` and `dump_triples`** (previously CLI-only flags).
- **`init` now drops `.pi/agent/AGENTS.md`** pointing at the root AGENTS.md, and
  **rewrites every generated artifact** (AGENTS.md block, claude.md instruction,
  Claude hook, pi extension) so old installs auto-update. Marker-bearing files
  are refreshed; user-authored files and `graph.json` are never touched.

### Changed
- **All agent instructions point at MCP tools** — the AGENTS.md template,
  claude.md stub, Claude hook block message, pi guard extension, and the pi skill.
- **Guard hooks block word-boundary matches anywhere in a command** (`git grep`,
  `sudo cat`, `xargs rg`), not just command position. `git cat-file` stays allowed.
- **Agent-written graph data survives re-ingest without ghosts.** Enrich
  descriptions map onto parser nodes by id (deleted/renamed functions are
  dropped, not resurrected); `add_entity` nodes are marked `agent_created` and
  re-added only while their file exists; the `agent_inferred` flag is now
  restored alongside the description.

## [4.1.0] - 2026-07-21

### Changed
- **pi integration now rides on `pi-mcp-adapter` + MCP instead of a bundled npm
  package.** Removed the `pi-package/` npm project, its template-sync scripts,
  and the npm-publish workflow. `codecompass setup-pi` (also auto-run on the
  first CLI / MCP-server invocation) wires pi globally: installs
  `pi-mcp-adapter` if missing, copies the skill to `~/.pi/agent/skills/`, and
  registers the `codecompass-mcp` server in `~/.config/mcp/mcp.json`.
- **`codecompass init` drops a lean pi guard extension** into
  `<repo>/.pi/extensions/` when pi is installed, blocking `grep`/`rg`/`cat` in
  pi the same way the Claude PreToolUse hook does. Project-local placement
  scopes it — no repo registry needed.

## [3.1.1] - 2026-07-11

### Fixed
- **PHP `use` imports now resolve to files via PSR-4.** `blast_radius`/`deps`
  read `composer.json`'s `autoload`/`autoload-dev` `psr-4` map, so
  `use GuzzleHttp\Client;` resolves to `src/Client.php`. This closes the last
  PHP gap in reverse blast radius — a class imported but not called (e.g. a
  constants class like `RequestOptions`) now correctly surfaces its dependents.

## [3.1.0] - 2026-07-11

### Added
- **Inheritance resolution for `super()` calls** across all call-based languages.
  `super().method()` (Python), `super.method()` (JS/TS), and `parent::method()`
  (PHP) now resolve to the parent class's method via a class→parent map, so
  `impact("Base.method")` captures subclass callers that delegate up. `self::`/
  `static::` (PHP) resolve to the enclosing class. Recovers callers that were
  previously left in the unresolved bucket (e.g. click's `Group.invoke` calling
  `super().invoke()` now shows under `Command.invoke`).

## [3.0.1] - 2026-07-11

### Fixed
- **`blast_radius` traversed the wrong direction.** It returned what the target
  *depends on* (forward), not what *depends on the target*. It now traverses in
  reverse and transitively — who calls / imports / inherits from the target —
  which is the "what breaks if I edit this" question the tool is for. An entry
  point that nothing imports now correctly returns few/no dependents (guzzle's
  `Client.php`) instead of a misleading list of its own dependencies.

## [3.0.0] - 2026-07-11

Major release: full-fidelity node identity, cross-language parity, and a
discovery toolkit. **Requires a re-ingest** (node ids changed).

### Added
- **Class-level node de-merge.** Node ids are now file- *and* class-qualified
  (`project:file:Class.method`), so same-named methods of different classes in
  the **same file** stay distinct (`Command.invoke` vs `Context.invoke` in
  click's `core.py`). Every definition and call carries `owner_class`; calls
  resolve to `owner == receiver_type` first.
- **PHP parity.** The PHP extractor gained receiver capture, type inference
  (`new X()`, `$this`, typed params, return-type inference), and
  visibility-based exports (`public` = API, `private`/`protected` = internal) —
  matching the JS/TS and Python extractors.
- **`grep` query** — regex search over graph entities (the graph-native
  replacement for grepping source).
- **Discovery decision guide** in the installed `AGENTS.md`
  (discover→trace→read→edit; `grep` a named concept first for vague features).

### Fixed
- **`hierarchy_builder` never indexed `.php`/`.jsx` files** — its extension set
  was out of sync with the parser, so PHP repos got no File nodes and
  `blast_radius`/`deps` by file returned nothing. (Guzzle: 1 → 90 File nodes.)
- **Impact bucket flood.** The unresolved-caller fallback now only fires when
  there's no precise answer, so a common name (`invoke`) no longer floods a
  query that already resolved.

### Benchmarks (see `docs/benchmark-results.md`)
- Tokens to a verified answer vs grep/read: requests −67%, click −82%,
  guzzle −66%, express −82%. Wins every relational/discovery task across
  JS, Python, and PHP.

## [2.8.0] - 2026-07-11

### Added
- **`grep` query — regex search over the graph.** The graph-native replacement
  for grepping source: full regex power over indexed entities
  (`--grep "^get_"`, `--grep ".*Adapter$"`), matching name/file/kind/description.
- **Discovery decision guide in the installed `AGENTS.md`** — a
  discover→trace→read→edit loop with a "which tool when" table. For a feature
  request that names a concept ("session timeout"), `grep` the concept first
  (cheap, precise); `map` is the fallback for truly nameless needs.

### Changed
- **Node-level de-merge.** Graph nodes are now file-qualified (`project:file:name`)
  with case preserved, so same-named entities stay distinct — `api.request` vs
  `Session.request`, `Session.send` vs `HTTPAdapter.send`, `class Session` vs a
  `session` function. Calls resolve to a specific definition at ingest using the
  captured receiver type (self / constructor / annotation / **return-type
  inference**), falling back to a name bucket when genuinely ambiguous. See
  `docs/node-demerge.md`. **Requires a re-ingest.**
- **`impact` callers now carry `line` and a `resolved` flag.** The real call-site
  file+line (from the edge, not the merged node) so verification reads a slice,
  not a whole function; `resolved: false` marks calls whose receiver couldn't be
  statically typed (surfaced, not dropped, and not claimed as precise).
- **Return-type inference** (Python + TS): `x = get_thing()` where `get_thing`
  declares `-> Foo` types `x` as `Foo`, so its method calls resolve.

### Fixed
- On a Flask/requests-scale benchmark these changes cut the impact task ~80%
  (de-merged, line-anchored, slice-verified) and flipped the tool from slower to
  faster than raw grep/read overall.

## [2.7.0] - 2026-07-11

### Added
- **`map` query** — a compact `{file: [symbols]}` index of the codebase
  (~37x leaner than `--tree`) for an agent to reason over during discovery.
  The semantic-discovery entry point for a vague task: read the map, use your
  own judgment to find where a feature belongs, then drill in with
  `flow`/`impact`/`deps`. On an Express ingest this cut the cost of orienting
  to a vague feature ("add response caching") from ~14k tokens (tree + old
  flows) to ~874.
- **`search` query** — keyword lookup over entity names/files/descriptions,
  OR-ranked, returning a lean candidate list. Use when you have a literal
  string/symbol to look for; prefer `map` when intent is semantic.

### Changed
- **`flow` is now lean by default** — returns only the call structure an agent
  needs (node name/kind/file/depth, edge from/to/type/order/line), no embedded
  source or rendered image. This roughly 5x'd the cost on wide flows before.
  The human-facing walkthrough (mermaid flowchart + prose narration, or
  source-embedded json) moved to a new **`flow_summary`** query.
- **Navigation guardrail retargeted and relaxed.** The `init`-installed
  PreToolUse hook (and pi extension) now block only code *search* (`grep`/`rg`,
  the Grep/Glob tools) and whole-file `cat` dumps — routing discovery through
  `--map`/`--search` — while leaving targeted reads (Read tool, `sed -n`,
  `head`/`tail`) free. Previously it hard-blocked all text search including
  cheap slice reads, which forced the graph onto tasks where grep is cheaper
  and blocked the grep-to-verify step the tools themselves recommend.

All three fixes below apply to both the JavaScript/TypeScript and Python
extractors (receiver capture, `new Foo()`/`Foo()` + annotation + `self`/`this`
type inference, and export/public-API awareness via `module.exports`/`export`
for JS and `__all__` + public class methods for Python).

### Fixed
- **`blast_radius` / `batch_impact` missed CommonJS importers.** The JS/TS
  parser now records `require('./x')` and dynamic `import('./x')` as IMPORTS
  edges (previously only ES `import` statements were recognized), and
  `get_blast_radius` resolves relative/dotted import specifiers to project
  files and adds direct importers to the result. Editing a file now surfaces
  the modules that `require()` it.
- **`impact` merged same-named methods on different receivers.** Call sites now
  carry the receiver expression (`app.handle` → `"app"`) and an inferred
  receiver *type*, so `find_callers` disambiguates same-named methods
  automatically. Receiver types are inferred from `new Router()`
  instantiations, TypeScript parameter/variable annotations, and class-method
  `this`; `impact "Router.handle"` then returns exactly the calls on a Router,
  name-independent, and a coincidental variable name never satisfies a typed
  query. `impact "app.handle"` filters by receiver, and every unqualified
  result row carries both `receiver` and `receiver_type` so collisions are
  fully visible. Node IDs are unchanged, so flow/trace/blast_radius are
  unaffected. (Receivers with no static type — a bare parameter later filled by
  a mixin, e.g. Express's `fn.handle` — stay name-matched; resolving those
  needs cross-function data-flow analysis.)
- **`dead_code` mis-flagged Python public API and dunder methods.** Dunder
  methods (`__call__`, `__get__`, `__getattr__`, …) are now treated as runtime
  entry points, and Python's public surface is recognized more completely —
  public (non-underscore) module-level functions and classes, not just class
  methods, are classified as public API. On a Flask ingest this cut the
  `src/flask` dead-code candidate list from 46 (37 of them public API or
  dunders) to 9 genuine underscore-private helpers.
- **`dead_code` flagged exported public API.** Definitions now track an
  `is_exported` flag from ES `export`, `module.exports = obj`, exports-object
  property assignments (`res.send = …`), chained `var app = exports =
  module.exports = {}` aliases, and `defineGetter`/`defineProperty`
  registrations. Exported symbols are classified as possible entry points
  rather than dead. (Functions reachable only via callbacks/`.bind()`/event
  emitters remain candidates — that needs data-flow analysis.)

## [2.6.2] - 2026-07-11

### Added
- CI: pushes to `main` now auto-publish to PyPI when `pyproject.toml`'s
  version changes, gated by a version-check job so routine pushes are a
  no-op (`.github/workflows/pypi-publish.yml`). This release is the first
  test of that pipeline.

## [2.6.1] - 2026-07-11

### Changed
- `AGENTS.md` broadens the re-ingest trigger from "after creating or deleting
  files" to "after any code change" (edits, additions, deletions, renames,
  refactors), so the graph stays current after routine edits too.

## [2.6.0] - 2026-07-11

### Added
- `codecompass init` (CLI and MCP) now scaffolds a `.claude/` enforcement
  layer alongside `.codecompass/`: `_ensure_claude_hooks()` writes
  `.claude/hooks/block-file-search.py` and merges the `PreToolUse` matchers
  (Bash, Grep, Glob) into `.claude/settings.json` without clobbering existing
  user hooks or settings.
- The installed hook blocks the Grep/Glob tools and code-reading shell
  commands (`cat`/`grep`/`rg`/`sed`/`awk`/`head`/`tail`/`less`) while leaving
  `ls`/`find`/`Read` open, so codebase navigation routes through the graph.
- MCP server (`mcp_server.py`) landed as `codecompass-mcp`, with tests.

## [2.5.0] - 2026-07-04

### Added
- `codecompass describe <repo_path>` — stages entity description work as batch
  files + `INSTRUCTIONS.md` under `.codecompass/describe/` for an agent swarm
  to fill in, rather than calling any single vendor's API. Any coding agent
  (Claude Code, Codex, Gemini, etc.) can dispatch its own native sub-agents
  against the staged batches, then run `describe --apply` to merge results
  into the graph and clean up. `ingest-code --describe` stages the same work
  as an optional Phase 5.
- `describe --apply` merges staged `batch_*.result.json` files into
  `.codecompass/graph.json` and removes the staging directory.
- `describe --force` allows re-staging over an in-progress run; without it,
  re-running `describe` while unmerged results exist raises an error instead
  of silently discarding them.
- AGENTS.md registration now includes an explicit "user-triggered ONLY" rule
  so agents don't run `describe` automatically after routine re-ingests.

### Changed
- `.codecompass/graph.json` is no longer gitignored — descriptions and graph
  structure are now committed so teams share the same enriched graph.
  `.codecompass/describe/` (transient staging) is gitignored instead.

## [2.4.0] - 2026-07-02

### Fixed
- PHP parsing was silently broken end-to-end: the loader called a nonexistent
  `tree_sitter_php` attribute, and the extractor matched node types from the
  wrong grammar version, so every `.php` file produced zero triples. Both are
  fixed and node types were re-verified against the installed grammar.
- Python extractor crashed ingestion on any file with a base class due to an
  undefined variable reference in the class-inheritance extraction path.

### Added
- Full PHP entity coverage: methods, properties (incl. constructor-promoted),
  class/interface/enum constants, enum cases, interfaces (multi-extends),
  traits (+ `use` composition), enums, namespace `use` imports, and
  `require`/`include`, plus every PHP call form (plain, method, nullsafe,
  static, `new`).
- `.jsx` file support in the code parser (`tree-sitter-javascript` already
  parses JSX; it was just missing from the extension/loader/extractor maps).

## [2.3.0] - 2026-07-01

### Added
- `codecompass init` now writes a "read `.codecompass` before making any changes or
  before reading any file" instruction into both `claude.md` and the `AGENTS.md` Code
  graph block, so agents surface this guidance automatically on init/re-ingest.
- PHP language support in the code parser: function/class/call extraction via
  `tree-sitter-php`, registered alongside the existing language extractors.

### Fixed
- `reader_agent.py` now only strips markdown code fences when the LLM response
  actually starts with one, instead of unconditionally.

### Removed
- Dropped the unused `chunk_pdf()` helper and its `PyPDF2` dependency.
- Dropped the unused `dry_run` parameter from `entity_resolver.resolve_entities()`.

## [2.2.0] - 2026-06-30

🚀 **The Foundation Release**

This release marks a major architectural migration to a lightweight, local-first graph structure and introduces powerful new traversal tools for AI agents and developers.

### 🌟 Key Highlights

#### 🏗️ Local-First Architecture
- **Bye-bye Neo4j**: Migrated from a heavy database dependency to a local NetworkX/JSON graph (`.codecompass/graph.json`).
- **Zero Config**: `codecompass init` now automatically initializes project state and handles `.gitignore` setup.
- **Project Memory**: Added persistent session knowledge via `.codecompass/` (overview, memory, and learnings files) to keep agents aligned across sessions.

#### 🗺️ Temporal Flow Tracing (`--flow`)
- **Execution Order**: Introduced DFS-based numbering for nodes and edges. The graph now reads as a strict sequence (Step 1 $\rightarrow$ Step 2 $\rightarrow$ Step N).
- **Multi-Format Output**: Support for Draw.io, Mermaid, and JSON.
- **Agent-Ready JSON**: Flow JSON now includes signatures, docstrings, and source snippets, allowing AI agents to narrate complex call stacks in plain English.
- **Forced Layout**: Implemented top-to-bottom vertical ranking in Mermaid for maximum readability.

#### ✂️ Dead-Code Analysis (`--dead-code`)
- Added a reachability analyzer to identify "dead" entities—functions or classes with no inbound callers or importers.
- Helps developers aggressively prune unused code with confidence.

#### 🛠️ Core Improvements
- **Metadata Enrichment**: Nodes now track `language`, `kind`, and `description` for better filtering.
- **Parser Fixes**: Improved resolution of private helper functions and method calls (`obj.method()`).
- **Clean Slate**: Fully removed all MCP-related configuration and obsolete Docker files.
