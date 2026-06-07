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
- `--plain` — compact output (~60% fewer tokens than rich table default)

## Hooks (auto-running)

| Hook | Script | Trigger |
|---|---|---|
| SessionStart | `scripts/session_start.py` | Every Claude session opens — injects `memory/` as context |
| Stop | `scripts/auto_memory.py` | Every Claude session ends — extracts new facts, writes to `memory/` |
| PostToolUse (Write/Edit) | `scripts/on_file_change.py` | Every file save — re-ingests changed file into code graph |
