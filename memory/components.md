# Key Components

## Read path (no API cost)

| Script | Purpose | Usage |
|---|---|---|
| `graph/query_cli.py` | Doc graph BFS keyword search | `python graph/query_cli.py "question" --hops 2` |
| `graph/code_query_cli.py` | Code graph traversal | `python -m graph.code_query_cli --deps file.py --project <name> --plain` |
| `graph/nav_agent.py` | Routes task text to correct graph tool | `python graph/nav_agent.py "task description" --project <name>` |

## Write path

| Script | Purpose | Usage |
|---|---|---|
| `graph/remember_batch_cli.py` | Write multiple facts at once | Pass JSON array of triples |
| `graph/remember_cli.py` | Write one fact | `python graph/remember_cli.py "A" "RELATION" "B"` |
| `graph/ingest_cli.py` | API-powered PDF/URL ingest (uses Haiku) | `--file paper.pdf` or `--url https://...` |

## code_query_cli flags (always use --plain)

- `--deps path/to/file.py` — what the file imports; use BEFORE editing any file
- `--impact FunctionName` — what calls this; use BEFORE renaming or removing
- `--trace EntryPoint` — full call chain forward from an entry point
- `--tree <project>` — folder/file hierarchy; use to orient before creating files
- `--blast-radius TARGET` — all files reachable from a symbol or file via CALLS/IMPORTS/INHERITS; use BEFORE editing anything to see the full change surface. Accepts a file path (`ingestion/file_watcher.py`) or symbol name (`write_code_triple`). Output: one file per line + `# blast radius: N files across M hops`.
- `--batch-impact file1.py file2.py ...` — union of blast radii across multiple targets; use when planning a multi-file change or PR. Each result line shows `[via: <source>]` and `[also in input]` when a dep is also an input target. Output: same as blast-radius but aggregated.
- `--styles ELEMENT` — what CSS selectors style this element (HTML/CSS/SCSS projects)
- `--plain` — compact output (~60% fewer tokens than rich table default)

## When to use which flag

| Scenario | Flag |
|---|---|
| About to edit one file or symbol | `--blast-radius` first, then `--deps` |
| Planning a PR that touches N files | `--batch-impact file1 file2 ...` |
| Renaming or removing a function | `--impact FunctionName` |
| Understanding a call chain | `--trace EntryPoint` |
| Orienting in an unfamiliar project | `--tree <project>` |
| Editing a CSS variable or HTML component | `--styles ElementName` |

## Ingested file types and edges

The code parser handles these languages and emits these edge types:

| Language | Edges emitted |
|---|---|
| Python, JS, TS, TSX | `CALLS`, `IMPORTS`, `INHERITS` |
| CSS, SCSS | `DEFINED_IN` (variable declarations), `USES_VAR` (usages), `IMPORTS` (@import/@use) |
| HTML | `REFERENCES` (custom element tags with a hyphen), `INCLUDES` (script/link tags) |
| `.styles.ts` (Lit) | `USES_VAR` (var() usages in css`...` blocks), `DEFINED_IN` (--custom-prop declarations) + all normal TS edges |

`--styles` queries the `STYLES` edge (CSS selector → HTML element). `--blast-radius` and `--batch-impact` traverse `CALLS`, `IMPORTS`, and `INHERITS` edges.

**Lit design token queries:** `.styles.ts` files (Lit web components) are parsed for CSS tokens inside `` css`...` `` template literals. Use `--impact "--tm-button-block-size" --project <name>` to find every `.styles.ts` file that uses a design token.

## Hooks (auto-running)

| Hook | Script | Trigger |
|---|---|---|
| SessionStart | `scripts/session_start.py` | Every Claude session opens — injects `memory/` as context |
| Stop | `scripts/auto_memory.py` | Every Claude session ends — extracts new facts, writes to `memory/` |
| PostToolUse (Write/Edit) | `scripts/on_file_change.py` | Every file save — re-ingests changed file into code graph |
