"""CodeCompass — code dependency index for LLM coding agents.

Commands:
    init <repo_path>
    ingest-code <repo_path> [--normalize] [--dump-triples <out.json>]
    load-triples <triples.json> <repo_path>
    watch <repo_path>
"""

import argparse
import sys
import os
import re
import json
from dotenv import load_dotenv
from rich.console import Console

from graph.code_graph_client import get_client
from ingestion.code_parser import parse_directory
from ingestion.hierarchy_builder import build_hierarchy, get_file_id_map
from ingestion.file_watcher import FileWatcher

load_dotenv(override=True)
console = Console()

_CODECOMPASS_START = "<!-- codecompass-code-graph-start -->"
_CODECOMPASS_END = "<!-- codecompass-code-graph-end -->"
_CODECOMPASS_READ_INSTRUCTION = (
    "Orient through the code graph first: start from an entry point, see what's "
    "there, then trace its flow and dependencies — never use `cat`, `grep`, or "
    "`rg` to search or read code content. Use the `codecompass query` commands "
    "below for discovery and tracing, then read only the specific slices the "
    "graph points you to."
)


def init_project(repo_path: str) -> None:
    """Initialize the .codecompass directory in the given repository."""
    repo_path = os.path.abspath(repo_path)
    compass_dir = os.path.join(repo_path, ".codecompass")

    os.makedirs(compass_dir, exist_ok=True)

    stubs = {
        "overview.md": (
            "# Project Overview\n\n"
            "**What this file is for:** the durable orientation a fresh session needs\n"
            "FIRST — what this repo is, what it does, its tech stack, and how to run\n"
            "it. Answers \"what am I looking at?\" Changes rarely.\n\n"
            "Save here: one-paragraph purpose, primary tech/languages, how to install\n"
            "and run, the main entry points. For recent activity, use `git log` — do\n"
            "NOT maintain a changelog here (it rots).\n"
        ),
        "memory.md": (
            "# Project Memory\n\n"
            "**What this file is for:** durable, factual context about what the code\n"
            "IS — architecture, data flow, module responsibilities, key entry points,\n"
            "and where important logic lives. Answers \"how is this project built?\"\n\n"
            "Save here: architectural decisions, data-flow walkthroughs, the role of\n"
            "key files/modules, pipeline structure. NOT debugging gotchas or\n"
            "surprises (those go in learnings.md).\n"
        ),
        "learnings.md": (
            "# Learnings\n\n"
            "**What this file is for:** hard-won, non-obvious insights — things that\n"
            "SURPRISED you or would trip up the next person. Answers \"what should I\n"
            "watch out for?\"\n\n"
            "Save here: gotchas, footguns, \"looks-X-but-is-actually-Y\" patterns,\n"
            "confirmed bugs/dead code, why a non-obvious approach was taken, things\n"
            "that cost you time to figure out. NOT the steady-state architecture\n"
            "(that goes in memory.md).\n"
        ),
    }

    for filename, content in stubs.items():
        file_path = os.path.join(compass_dir, filename)
        if not os.path.exists(file_path):
            with open(file_path, "w") as f:
                f.write(content)

    # ponytail: minimal way to create claude.md in repo root
    claude_md_path = os.path.join(repo_path, "claude.md")
    if not os.path.exists(claude_md_path):
        with open(claude_md_path, "w") as f:
            f.write(f"AGENTS.md\n\n{_CODECOMPASS_READ_INSTRUCTION}\n")
    else:
        with open(claude_md_path) as f:
            claude_md_content = f.read()
        if _CODECOMPASS_READ_INSTRUCTION not in claude_md_content:
            with open(claude_md_path, "a") as f:
                if claude_md_content and not claude_md_content.endswith("\n"):
                    f.write("\n")
                f.write(f"\n{_CODECOMPASS_READ_INSTRUCTION}\n")

    _ensure_gitignore(repo_path)
    _ensure_claude_hooks(repo_path)
    console.print(f"[bold green]Initialized CodeCompass in:[/] {compass_dir}")
    _register_project_agents_md(repo_path)


_GITIGNORE_ENTRIES = [
    (".codecompass/describe/", "# CodeCompass transient describe-swarm staging dir"),
]


def _ensure_gitignore(repo_path: str) -> None:
    """Add generated/transient CodeCompass artifacts to .gitignore (notes are kept)."""
    gitignore_path = os.path.join(repo_path, ".gitignore")

    lines = []
    if os.path.exists(gitignore_path):
        with open(gitignore_path) as f:
            lines = f.read().splitlines()

    missing = [(entry, comment) for entry, comment in _GITIGNORE_ENTRIES
               if not any(line.strip() == entry for line in lines)]
    if not missing:
        return

    with open(gitignore_path, "a") as f:
        if lines and lines[-1].strip():
            f.write("\n")
        for entry, comment in missing:
            f.write(comment + "\n")
            f.write(entry + "\n")


# The PreToolUse hook that blocks code *search* and whole-file dumps, but allows
# targeted reads. Discovery must go through the graph (--map / --search to find
# what's relevant, then --flow/--impact/--deps to trace), so raw text search
# (grep/rg and the Grep/Glob tools) is blocked. Whole-file `cat` is blocked too:
# read targeted slices with the Read tool (or sed -n/head/tail) once you know
# what to open.
_CLAUDE_HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""PreToolUse hook: block code search and whole-file dumps; allow targeted reads.

Installed by `codecompass init`. Safe to edit — init will not overwrite an existing copy.
"""
import json
import re
import sys

# Search tools/commands and whole-file dumps — blocked. Use the graph to
# discover, then read targeted slices.
_BLOCKED_TOOLS = {"Grep", "Glob"}
_BLOCKED_SHELL_RE = re.compile(r"(?:^|[;|&]|&&|\|\|)\s*(grep|rg|cat)(?:\s|$)")

_REASON = (
    "Don't use {what}. Discover through the graph — `codecompass query --map` "
    "(compact index to reason over) or `--search <kw>`, then `--flow`/`--impact`/"
    "`--deps` to trace — then read the specific slice you need with the Read tool "
    "(or `sed -n`/`head`/`tail`), not a whole-file dump."
)


def main() -> None:
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool_name in _BLOCKED_TOOLS:
        print(_REASON.format(what=f"the {tool_name} tool"), file=sys.stderr)
        sys.exit(2)

    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if _BLOCKED_SHELL_RE.search(command):
            print(_REASON.format(what="grep/rg/cat"), file=sys.stderr)
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
'''

# Tool names that should route through the block-file-search hook.
_CLAUDE_HOOK_MATCHERS = ("Bash", "Grep", "Glob")
_CLAUDE_HOOK_COMMAND = "python3 .claude/hooks/block-file-search.py"


def _ensure_claude_hooks(repo_path: str) -> None:
    """Install the codecompass PreToolUse guardrail into the repo's .claude/ config.

    Writes .claude/hooks/block-file-search.py (never overwriting an existing copy)
    and merges the PreToolUse matchers into .claude/settings.json without clobbering
    any hooks the user already configured.
    """
    claude_dir = os.path.join(repo_path, ".claude")
    hooks_dir = os.path.join(claude_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    hook_path = os.path.join(hooks_dir, "block-file-search.py")
    if not os.path.exists(hook_path):
        with open(hook_path, "w") as f:
            f.write(_CLAUDE_HOOK_SCRIPT)
        os.chmod(hook_path, 0o755)

    settings_path = os.path.join(claude_dir, "settings.json")
    settings: dict = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                settings = json.load(f) or {}
        except (json.JSONDecodeError, ValueError):
            console.print(
                f"[yellow]Could not parse {settings_path}; leaving it untouched. "
                "Add the codecompass PreToolUse hook manually.[/]"
            )
            return

    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])

    changed = False
    for matcher in _CLAUDE_HOOK_MATCHERS:
        entry = next((e for e in pre if e.get("matcher") == matcher), None)
        if entry is None:
            pre.append({
                "matcher": matcher,
                "hooks": [{"type": "command", "command": _CLAUDE_HOOK_COMMAND}],
            })
            changed = True
            continue
        entry_hooks = entry.setdefault("hooks", [])
        if not any(h.get("command") == _CLAUDE_HOOK_COMMAND for h in entry_hooks):
            entry_hooks.append({"type": "command", "command": _CLAUDE_HOOK_COMMAND})
            changed = True

    if changed:
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")


def ingest_code(repo_path: str, normalize: bool = False, dump_triples: str | None = None, describe: bool = False) -> None:
    """Ingest a codebase into the local code knowledge graph.

    Phase 1: Walk the repo and write the Project → Folder → File skeleton.
    Phase 2: Parse every source file with tree-sitter into CodeTriples.
    Phase 3: Normalize entity names via Haiku (only if --normalize is passed).
    Phase 4: Write all triples to the local graph.json.
    Phase 5 (optional): Stage entity descriptions for an agent swarm to fill in.
    """
    import json

    repo_path = os.path.abspath(repo_path)
    project_name = os.path.basename(repo_path)
    console.print(f"[bold blue]Ingesting codebase:[/] {repo_path}")

    if not os.path.exists(os.path.join(repo_path, ".codecompass")):
        console.print("[yellow]No .codecompass folder found — running init first...[/]")
        init_project(repo_path)

    client = get_client(repo_path)
    client.graph.clear()

    console.print("[dim]Phase 1/4 — Building hierarchy…[/]")
    file_id_map = build_hierarchy(repo_path, project_name, client)
    console.print(f"[dim]  {len(file_id_map)} source files indexed[/]")

    console.print("[dim]Phase 2/4 — Parsing source files…[/]")
    raw_triples = parse_directory(repo_path, progress=True)
    console.print(f"[dim]  {len(raw_triples)} raw triples extracted[/]")

    if not raw_triples:
        console.print("[yellow]No triples extracted — check that the repo contains supported files.[/]")
        client.close()
        return

    if dump_triples:
        data = [
            {
                "from_entity": t.from_entity,
                "from_type": t.from_type,
                "relation_type": t.relation_type,
                "to_entity": t.to_entity,
                "to_type": t.to_type,
                "source_file": t.source_file,
                "line_number": t.line_number,
            }
            for t in raw_triples
        ]
        with open(dump_triples, "w") as f:
            json.dump(data, f, indent=2)
        client.close()
        console.print(f"[bold green]Dumped {len(raw_triples)} raw triples to:[/] {dump_triples}")
        return

    if normalize:
        from ingestion.code_normalizer import normalize_triples
        console.print("[dim]Phase 3/4 — Normalizing triples via Haiku…[/]")
        triples = normalize_triples(raw_triples, progress=True)
        console.print(f"[dim]  {len(triples)} triples after normalization[/]")
    else:
        console.print("[dim]Phase 3/4 — Skipping normalization (pass --normalize to enable)[/]")
        triples = raw_triples

    console.print("[dim]Phase 4/4 — Writing to local graph…[/]")
    written = client.write_code_triples_batch(triples, file_id_map, project_name)

    total_nodes = client.node_count()
    client.close()

    console.print(
        f"[bold green]Done.[/] Wrote {written} triples. "
        f"Graph now has {total_nodes} nodes."
    )
    _register_project_agents_md(repo_path)

    if describe:
        from ingestion.description_enricher import prepare_describe_batches
        console.print("[dim]Phase 5/5 — Staging descriptions for the agent swarm…[/]")
        staged = prepare_describe_batches(repo_path)
        if staged["num_entities"] == 0:
            console.print("[dim]  Nothing to describe.[/]")
        else:
            console.print(
                f"[bold green]Staged[/] {staged['num_entities']} entities in "
                f"{staged['num_batches']} batch(es). Read {staged['instructions_path']} "
                "and dispatch a sub-agent per batch, then run "
                f"`codecompass describe {repo_path} --apply`."
            )


def _register_project_agents_md(repo_path: str) -> None:
    """Write or update the Code graph section in the project's AGENTS.md."""
    block = f"""{_CODECOMPASS_START}
<!-- This file must stay byte-for-byte identical to its counterpart in pi-package/templates/. Run scripts/check-pi-package-sync.sh to verify. -->
## Code graph

**{_CODECOMPASS_READ_INSTRUCTION}**

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

   Use the Read tool with `offset` and `limit`, or shell snippets like
   `sed -n 'START,ENDp'`, `head`, and `tail`, to pull only the function or
   slice the graph identified. For edits, use the edit tool with exact matched
   text; rewrite the smallest slice that works, not the whole file.

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
{_CODECOMPASS_END}"""

    agents_md_path = os.path.join(repo_path, "AGENTS.md")

    if os.path.exists(agents_md_path):
        with open(agents_md_path) as f:
            content = f.read()
        if _CODECOMPASS_START in content:
            pattern = re.escape(_CODECOMPASS_START) + r".*?" + re.escape(_CODECOMPASS_END)
            new_content = re.sub(pattern, block, content, flags=re.DOTALL)
        else:
            new_content = content.rstrip() + f"\n\n---\n\n{block}\n"
    else:
        new_content = block + "\n"

    with open(agents_md_path, "w") as f:
        f.write(new_content)

    console.print(f"[dim]  Registered in {agents_md_path}[/]")


def load_triples(triples_file: str, repo_path: str) -> None:
    """Load pre-normalized triples from a JSON file into the local graph."""
    import json
    from models.code_types import CodeTriple

    repo_path = os.path.abspath(repo_path)
    project_name = os.path.basename(repo_path)

    with open(triples_file) as f:
        data = json.load(f)

    triples = [
        CodeTriple(
            from_entity=d["from_entity"],
            from_type=d["from_type"],
            relation_type=d["relation_type"],
            to_entity=d["to_entity"],
            to_type=d["to_type"],
            source_file=d["source_file"],
            line_number=d["line_number"],
        )
        for d in data
    ]

    console.print(f"[bold blue]Loading {len(triples)} triples into {repo_path}[/]")
    client = get_client(repo_path)
    file_id_map = get_file_id_map(repo_path, project_name, client)

    written = client.write_code_triples_batch(triples, file_id_map, project_name)
    total_nodes = client.node_count()
    client.close()
    console.print(f"[bold green]Done.[/] Wrote {written} triples. Graph now has {total_nodes} nodes.")


def watch_code(repo_path: str) -> None:
    """Watch a repo for file changes and keep the local graph updated incrementally."""
    repo_path = os.path.abspath(repo_path)
    project_name = os.path.basename(repo_path)
    client = get_client(repo_path)
    file_id_map = build_hierarchy(repo_path, project_name, client)
    watcher = FileWatcher(repo_path, project_name, client, file_id_map)
    watcher.start()


def main():
    prog = "codecompass"
    parser = argparse.ArgumentParser(
        prog=prog,
        description="CodeCompass — code dependency index for LLM coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_init = subparsers.add_parser("init", help="Initialize .codecompass/ in a repo")
    p_init.add_argument("repo_path", nargs="?", default=".")

    p_ingest = subparsers.add_parser("ingest-code", help="Index a repo into the local graph")
    p_ingest.add_argument("repo_path", nargs="?", default=".")
    p_ingest.add_argument("--normalize", action="store_true")
    p_ingest.add_argument("--dump-triples", metavar="OUT")
    p_ingest.add_argument("--describe", action="store_true")

    p_describe = subparsers.add_parser("describe", help="Stage or apply entity descriptions")
    p_describe.add_argument("repo_path", nargs="?", default=".")
    p_describe.add_argument("--batch-size", type=int, default=15)
    p_describe.add_argument("--force", action="store_true")
    p_describe.add_argument("--apply", action="store_true")

    p_load = subparsers.add_parser("load-triples", help="Load pre-normalized triples into the graph")
    p_load.add_argument("triples_file")
    p_load.add_argument("repo_path")

    p_watch = subparsers.add_parser("watch", help="Watch a repo and keep the graph updated")
    p_watch.add_argument("repo_path", nargs="?", default=".")

    p_mcp = subparsers.add_parser("mcp", help="Run the MCP server")
    p_mcp.add_argument("repo_path", nargs="?", default=".")

    subparsers.add_parser("query", help="Run a graph query (passes through to code_query_cli)")

    args, unknown = parser.parse_known_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if unknown and args.command != "query":
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    if args.command == "init":
        init_project(args.repo_path)

    elif args.command == "ingest-code":
        ingest_code(
            args.repo_path,
            normalize=args.normalize,
            dump_triples=args.dump_triples,
            describe=args.describe,
        )

    elif args.command == "describe":
        if args.apply:
            from ingestion.description_enricher import apply_describe_results
            updated = apply_describe_results(args.repo_path)
            console.print(f"[bold green]Applied[/] descriptions for {updated} entities.")
        else:
            from ingestion.description_enricher import prepare_describe_batches
            staged = prepare_describe_batches(
                args.repo_path, batch_size=args.batch_size, force=args.force
            )
            if staged["num_entities"] == 0:
                console.print("[dim]Nothing to describe.[/]")
            else:
                console.print(
                    f"[bold green]Staged[/] {staged['num_entities']} entities in "
                    f"{staged['num_batches']} batch(es) at {staged['describe_dir']}.\n"
                    f"Read {staged['instructions_path']} and dispatch a sub-agent per "
                    f"batch, then run `codecompass describe {args.repo_path} --apply`."
                )

    elif args.command == "load-triples":
        load_triples(args.triples_file, args.repo_path)

    elif args.command == "query":
        from graph.code_query_cli import main as query_main
        sys.argv = [f"{prog} query"] + unknown
        query_main()

    elif args.command == "watch":
        watch_code(args.repo_path)

    elif args.command == "mcp":
        if args.repo_path != ".":
            os.environ["CODECOMPASS_REPO"] = os.path.abspath(args.repo_path)
        from mcp_server import main as mcp_main
        mcp_main()


if __name__ == "__main__":
    main()
