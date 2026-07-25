<!-- Installed by `codecompass init` — rewritten on every init. -->
Read `.agents/codecompass.md` first — it contains the CodeCompass code-graph instructions for this repo.

Orient through the code graph first: start from an entry point, see what's there, then trace its flow and dependencies — never use `cat`, `grep`, or `rg` to search or read code content. Use the codecompass MCP tools below for discovery and tracing, then read only the specific slices the graph points you to.

### Code exploration requirements

- [ ] Explore only through the codecompass tools — `grep`/`search`/`tree` to discover, `flow`/`deps` to understand. Never `grep`/`cat`/`rg` the repo directly.
- [ ] Trace the `flow` of every code path you are about to touch BEFORE editing.
- [ ] Run `impact`/`blast_radius` on every symbol and file you will change — before the edit, and again after to confirm the actual fallout.
- [ ] Graph missing something or wrong? Fix it the moment you notice: `add_entity` / `add_call`.
- [ ] `ingest` after every edit session, then flush what you learned into the graph with `add_entity` / `add_call`.
