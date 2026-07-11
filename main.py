"""CodeCompass — code dependency index for LLM coding agents.

Commands:
    init <repo_path>
    ingest-code <repo_path> [--normalize] [--dump-triples <out.json>]
    load-triples <triples.json> <repo_path>
    watch <repo_path>
"""

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
    "Read `.codecompass` before making any changes or before reading any file. "
    "If you think codecompass will help in any way, use it."
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


# The PreToolUse hook that forces codecompass for codebase navigation. Blocks the
# Grep and Glob tools outright and catches the common code-reading shell commands
# (cat/grep/rg/sed/awk/head/tail/less). Read is intentionally left alone: it is the
# terminal step of the workflow ("find the entity with codecompass, then read it"),
# and a stateless hook cannot tell whether codecompass was consulted first.
_CLAUDE_HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""PreToolUse hook: force codecompass for codebase navigation instead of raw file search.

Installed by `codecompass init`. Safe to edit — init will not overwrite an existing copy.
"""
import json
import re
import sys

# Tools that codecompass unambiguously replaces for code navigation/search.
_BLOCKED_TOOLS = {"Grep", "Glob"}
# Code-reading shell commands. Read a specific known file via the Read tool instead.
_BLOCKED_SHELL_RE = re.compile(
    r"(?:^|[;|&]|&&|\|\|)\s*(cat|grep|rg|sed|awk|head|tail|less)(?:\s|$)"
)

_REASON = (
    "Codebase navigation must use codecompass, not {what}. "
    "Use `codecompass query --tree|--blast-radius|--impact|--deps|--flow` to find "
    "the entity/file, then `read` it directly. "
    "(`ls`/`find` are fine for non-code exploration — build output, "
    "confirming a file was created, listing fixtures/assets.)"
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
            print(_REASON.format(what="cat/grep/rg/sed/awk/head/tail/less shell commands"),
                  file=sys.stderr)
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
## Code graph

**{_CODECOMPASS_READ_INSTRUCTION}**

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
1. **Before editing any file**, run `--blast-radius` on it to see what depends on it:
   ```bash
   codecompass query --blast-radius <file_or_symbol>
   ```
2. **Before calling or importing a symbol you haven't read**, run `--impact` to
   understand its downstream effects:
   ```bash
   codecompass query --impact <symbol>
   ```
3. **After creating or deleting files**, re-ingest so the graph stays current:
   ```bash
   codecompass ingest-code
   ```
4. **Never skip step 1.** Reading a file without checking its blast radius first
   means you may miss callers, importers, or CSS/HTML dependents.

### Graph vs. `ls`/`find` — how to decide

Use **codecompass** when the question is about code structure or relationships:
"what calls this", "what depends on this file", "what does this module do",
"how does this flow work", "is this dead code". The graph knows the real
dependency edges; a directory listing does not.

Use **`ls`/`find`** when the question has nothing to do with code
relationships: confirming a generated/output file exists, listing a
build/dist/log directory, checking test fixtures or assets, or any path the
graph doesn't index. These are fine — don't force codecompass onto questions
it can't answer.

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
invocation are invisible. Treat every result as a candidate — grep the name
across the repo to confirm it is truly unused before deleting it.

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

- After adding, renaming, or deleting source files
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
    usage = (
        f"[bold]Usage:[/]\n"
        f"  {prog} init [italic]<repo_path>[/]\n"
        f"  {prog} ingest-code [italic]<repo_path>[/] [--normalize] [--dump-triples [italic]<out.json>[/]] [--describe]\n"
        f"  {prog} describe [italic]<repo_path>[/] [--batch-size N] [--force] [--apply]\n"
        f"  {prog} query [italic]<--flag> <arg> <repo_path>[/]\n"
        f"  {prog} load-triples [italic]<triples.json> <repo_path>[/]\n"
        f"  {prog} watch [italic]<repo_path>[/]\n"
        f"  {prog} mcp [italic]<repo_path>[/]"
    )

    if len(sys.argv) < 2:
        console.print(usage)
        sys.exit(1)

    command = sys.argv[1]

    if command == "init":
        args = sys.argv[2:]
        init_project(args[0] if args else ".")

    elif command == "ingest-code":
        args = sys.argv[2:]
        non_flag_args = [a for a in args if not a.startswith("--")]
        repo_path = non_flag_args[0] if non_flag_args else "."
        normalize = "--normalize" in args
        describe = "--describe" in args
        dump_triples = None
        if "--dump-triples" in args:
            idx = args.index("--dump-triples")
            if idx + 1 < len(args):
                dump_triples = args[idx + 1]
        ingest_code(repo_path, normalize=normalize, dump_triples=dump_triples, describe=describe)

    elif command == "describe":
        args = sys.argv[2:]
        repo_path = "."
        batch_size = 15
        apply = "--apply" in args
        force = "--force" in args
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--batch-size" and i + 1 < len(args):
                batch_size = int(args[i + 1])
                i += 2
            elif a in ("--apply", "--force"):
                i += 1
            else:
                repo_path = a
                i += 1

        if apply:
            from ingestion.description_enricher import apply_describe_results
            updated = apply_describe_results(repo_path)
            console.print(f"[bold green]Applied[/] descriptions for {updated} entities.")
        else:
            from ingestion.description_enricher import prepare_describe_batches
            staged = prepare_describe_batches(repo_path, batch_size=batch_size, force=force)
            if staged["num_entities"] == 0:
                console.print("[dim]Nothing to describe.[/]")
            else:
                console.print(
                    f"[bold green]Staged[/] {staged['num_entities']} entities in "
                    f"{staged['num_batches']} batch(es) at {staged['describe_dir']}.\n"
                    f"Read {staged['instructions_path']} and dispatch a sub-agent per "
                    f"batch, then run `codecompass describe {repo_path} --apply`."
                )

    elif command == "load-triples":
        args = sys.argv[2:]
        if len(args) < 2:
            console.print(f"[red]Usage: {prog} load-triples <triples.json> <repo_path>[/]")
            sys.exit(1)
        load_triples(args[0], args[1])

    elif command == "query":
        from graph.code_query_cli import main as query_main
        sys.argv = [f"{prog} query"] + sys.argv[2:]
        query_main()

    elif command == "setup":
        from graph.setup import run_setup
        run_setup()

    elif command == "watch":
        args = sys.argv[2:]
        watch_code(args[0] if args else ".")

    elif command == "mcp":
        args = sys.argv[2:]
        if args:
            os.environ["CODECOMPASS_REPO"] = os.path.abspath(args[0])
        from mcp_server import main as mcp_main
        mcp_main()

    else:
        console.print(f"[red]Unknown command:[/] {command}\n")
        console.print(usage)
        sys.exit(1)


if __name__ == "__main__":
    main()
