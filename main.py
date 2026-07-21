"""CodeCompass — code dependency index for LLM coding agents.

Commands:
    enrich <repo_path> [--apply]
    load-triples <triples.json> <repo_path>
    watch <repo_path>
    mcp [repo_path]
    setup-pi

Indexing (init / ingest-code) and agent writes (add-entity / add-call) are
MCP tools — agents use the server, not this CLI.
"""

import argparse
import sys
import os
import re
import json
import shutil
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
    "`rg` to search or read code content. Use the codecompass MCP tools below "
    "for discovery and tracing, then read only the specific slices the graph "
    "points you to."
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

    # ponytail: minimal way to create claude.md in repo root. Existing copies
    # get their instruction line refreshed so old versions auto-update.
    claude_md_path = os.path.join(repo_path, "claude.md")
    if not os.path.exists(claude_md_path):
        with open(claude_md_path, "w") as f:
            f.write(f"AGENTS.md\n\n{_CODECOMPASS_READ_INSTRUCTION}\n")
    else:
        with open(claude_md_path) as f:
            claude_md_content = f.read()
        lines = claude_md_content.splitlines()
        refreshed = False
        for i, line in enumerate(lines):
            if line.startswith("Orient through the code graph first") and line != _CODECOMPASS_READ_INSTRUCTION:
                lines[i] = _CODECOMPASS_READ_INSTRUCTION
                refreshed = True
        if refreshed:
            with open(claude_md_path, "w") as f:
                f.write("\n".join(lines) + ("\n" if claude_md_content.endswith("\n") else ""))
        elif _CODECOMPASS_READ_INSTRUCTION not in claude_md_content:
            with open(claude_md_path, "a") as f:
                if claude_md_content and not claude_md_content.endswith("\n"):
                    f.write("\n")
                f.write(f"\n{_CODECOMPASS_READ_INSTRUCTION}\n")

    _ensure_gitignore(repo_path)
    _ensure_claude_hooks(repo_path)
    _ensure_pi_extension(repo_path)
    _ensure_pi_agents_md(repo_path)
    _register_repo(repo_path)
    console.print(f"[bold green]Initialized CodeCompass in:[/] {compass_dir}")
    _register_project_agents_md(repo_path)


_GITIGNORE_ENTRIES = [
    (".codecompass/enrich/", "# CodeCompass transient enrich-swarm staging dir"),
    (".codecompass/vectors.lance/", "# CodeCompass vector index (rebuilt on ingest)"),
]


def _repos_registry_path() -> str:
    """Global registry of codecompass repos, one absolute path per line."""
    return os.environ.get(
        "CODECOMPASS_REPOS",
        os.path.join(os.path.expanduser("~"), ".codecompass", "repos"))


def _register_repo(repo_path: str) -> None:
    """Add the repo to the global registry so guard hooks block only reads
    inside a codecompass project and allow everything outside one."""
    try:
        registry = _repos_registry_path()
        os.makedirs(os.path.dirname(registry), exist_ok=True)
        existing = set()
        if os.path.exists(registry):
            with open(registry) as f:
                existing = {line.strip() for line in f if line.strip()}
        abs_path = os.path.abspath(repo_path)
        if abs_path not in existing:
            with open(registry, "a") as f:
                f.write(abs_path + "\n")
    except OSError:
        pass


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
# targeted reads. Discovery must go through the graph (the codecompass MCP `grep`
# tool to find what's relevant, then `flow`/`impact`/`deps` to trace), so raw
# text search (grep/rg and the Grep/Glob tools) is blocked. Whole-file `cat` is
# blocked too: read targeted slices with the Read tool (or sed -n/head/tail)
# once you know what to open.
_CLAUDE_HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""PreToolUse hook: block code search and whole-file dumps INSIDE codecompass
projects; allow reads outside any registered repo (no graph exists there).

Installed by the codecompass `init` tool. Safe to edit — init only rewrites copies it installed.
"""
import json
import os
import re
import sys

# This project's root, baked in at init time — fallback when the global
# registry of codecompass repos is missing.
_REPO = __CODECOMPASS_REPO__
_REGISTRY = os.environ.get(
    "CODECOMPASS_REPOS", os.path.expanduser("~/.codecompass/repos"))

_BLOCKED_TOOLS = {"Grep", "Glob"}
# Word-boundary match anywhere in the command: catches `grep foo`,
# `git grep foo`, `sudo cat f`, `xargs rg` — not just command position.
# (?![\w-]) avoids false positives like `git cat-file`.
_BLOCKED_SHELL_RE = re.compile(r"\b(?:grep|rg|cat)\b(?![\w-])")


def _repos() -> list:
    try:
        with open(_REGISTRY) as f:
            repos = [line.strip() for line in f if line.strip()]
        return repos or [_REPO]
    except OSError:
        return [_REPO]


def _repo_containing(path: str):
    """The registered codecompass repo containing path, or None."""
    for repo in _repos():
        if path == repo or path.startswith(repo + os.sep):
            return repo
    return None


def _resolve(token: str, cwd: str) -> str:
    p = os.path.expanduser(token)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def _block(what: str) -> None:
    print(
        f"Don't use {what}. Discover through the codecompass MCP tools — "
        "`grep` to find what's relevant, then `flow`/`impact`/`deps` to trace — "
        "then read the specific slice you need with the Read tool (or "
        "`sed -n`/`head`/`tail`), not a whole-file dump.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    cwd = payload.get("cwd") or os.getcwd()

    if tool_name in _BLOCKED_TOOLS:
        target = _resolve(tool_input.get("path") or cwd, cwd)
        repo = _repo_containing(target)
        if repo:
            _block(f"the {tool_name} tool")
        sys.exit(0)  # outside every codecompass repo — no graph to route through

    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if _BLOCKED_SHELL_RE.search(command):
            saw_path = False
            # ponytail: naive whitespace split — quoted paths with spaces don't
            # resolve and fall through to the conservative cwd check.
            for tok in command.split():
                if tok.startswith("-"):
                    continue
                p = _resolve(tok, cwd)
                if not os.path.exists(p):
                    continue
                saw_path = True
                repo = _repo_containing(p)
                if repo:
                    _block("grep/rg/cat")
            if not saw_path:  # unparseable — decide by where the agent stands
                repo = _repo_containing(os.path.realpath(cwd))
                if repo:
                    _block("grep/rg/cat")
            # every named path is outside all codecompass repos — allow

    sys.exit(0)


if __name__ == "__main__":
    main()
'''

# Tool names that should route through the block-file-search hook.
_CLAUDE_HOOK_MATCHERS = ("Bash", "Grep", "Glob")
# $CLAUDE_PROJECT_DIR resolves to the project root, not the agent's cwd.
_CLAUDE_HOOK_COMMAND = 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/block-file-search.py"'
_OLD_CLAUDE_HOOK_COMMAND = "python3 .claude/hooks/block-file-search.py"


_GENERATED_MARKERS = ("Installed by `codecompass init`",
                      "Installed by the codecompass `init` tool")


def _is_generated(path: str) -> bool:
    """True if path is a file init installed (carries our marker) — those get
    rewritten on every init so old versions auto-update. Files without the
    marker are user-authored and left alone."""
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        return False
    return any(m in content for m in _GENERATED_MARKERS)


def _ensure_claude_hooks(repo_path: str) -> None:
    """Install the codecompass PreToolUse guardrail into the repo's .claude/ config.

    Writes .claude/hooks/block-file-search.py, rewriting any copy init previously
    installed (marker-bearing) so old versions auto-update. Merges the PreToolUse
    matchers into .claude/settings.json without clobbering any hooks the user
    already configured.
    """
    claude_dir = os.path.join(repo_path, ".claude")
    hooks_dir = os.path.join(claude_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    hook_path = os.path.join(hooks_dir, "block-file-search.py")
    script = _CLAUDE_HOOK_SCRIPT.replace(
        "__CODECOMPASS_REPO__", json.dumps(os.path.abspath(repo_path)))
    if not os.path.exists(hook_path) or _is_generated(hook_path):
        with open(hook_path, "w") as f:
            f.write(script)
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
        for h in entry_hooks:  # migrate pre-$CLAUDE_PROJECT_DIR command paths
            if h.get("command") == _OLD_CLAUDE_HOOK_COMMAND:
                h["command"] = _CLAUDE_HOOK_COMMAND
                changed = True
        if not any(h.get("command") == _CLAUDE_HOOK_COMMAND for h in entry_hooks):
            entry_hooks.append({"type": "command", "command": _CLAUDE_HOOK_COMMAND})
            changed = True

    if changed:
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")


# pi has no settings-level tool guard, only extensions can veto a tool call.
# This is the pi analog of the Claude PreToolUse hook: dropped into the repo's
# .pi/extensions/, it loads only in this trusted project, so it blocks
# unconditionally here — no repo registry needed, placement scopes it.
# ponytail: blocks any grep/rg/cat while working in this project, even against a
# path outside the repo. Add path-scoping like the Claude hook if that bites.
_PI_GUARD_EXT = r'''// Installed by the codecompass `init` tool into .pi/extensions/.
// Blocks raw text search (grep/rg) and whole-file dumps (cat) so discovery
// routes through the codecompass graph. Loads only in this trusted project.
// Safe to edit — init only rewrites copies that carry this marker.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Word-boundary match anywhere in the command: catches `grep foo`,
// `git grep foo`, `sudo cat f`, `xargs rg` — not just command position.
// (?![\w-]) avoids false positives like `git cat-file`.
const BLOCKED_SHELL_RE = /\b(?:grep|rg|cat)\b(?![\w-])/;

const REASON =
  "Don't grep/cat/rg the repo. Discover through the codecompass MCP tools — " +
  "`grep` to find what's relevant, then `flow`/`impact`/`deps` to trace — " +
  "then read the specific slice with the Read tool (or sed -n/head/tail), " +
  "not a whole-file dump.";

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    if (event.toolName === "grep") {
      return { block: true, reason: REASON };
    }
    if (event.toolName === "bash") {
      const command = String((event.input as { command?: string }).command ?? "");
      if (BLOCKED_SHELL_RE.test(command)) {
        return { block: true, reason: REASON };
      }
    }
    return undefined;
  });
}
'''


def _ensure_pi_extension(repo_path: str) -> None:
    """Drop the pi guard extension into <repo>/.pi/extensions/ so pi blocks
    grep/cat/rg the same way the Claude hook does. No-op when pi is not
    installed. Rewrites copies init previously installed so old versions
    auto-update; leaves user-authored extensions alone."""
    if shutil.which("pi") is None:
        return
    ext_dir = os.path.join(repo_path, ".pi", "extensions")
    ext_path = os.path.join(ext_dir, "codecompass-guard.ts")
    if os.path.exists(ext_path) and not _is_generated(ext_path):
        return
    os.makedirs(ext_dir, exist_ok=True)
    with open(ext_path, "w") as f:
        f.write(_PI_GUARD_EXT)


def _ensure_pi_agents_md(repo_path: str) -> None:
    """Drop .pi/agent/AGENTS.md pointing at the root AGENTS.md so pi picks up
    the CodeCompass instructions. No-op when pi is not installed. Rewrites
    copies init previously installed so old versions auto-update."""
    if shutil.which("pi") is None:
        return
    agents_path = os.path.join(repo_path, ".pi", "agent", "AGENTS.md")
    if os.path.exists(agents_path):
        with open(agents_path) as f:
            existing = f.read()
        if not (_is_generated(agents_path) or "See AGENTS.md in the project root" in existing):
            return  # user-authored — leave it alone
    os.makedirs(os.path.dirname(agents_path), exist_ok=True)
    with open(agents_path, "w") as f:
        f.write(
            "<!-- Installed by the codecompass `init` tool — rewritten on every init. -->\n"
            "See AGENTS.md in the project root — it contains the CodeCompass "
            "code-graph instructions for this repo.\n"
        )


def ingest_code(repo_path: str, normalize: bool = False, dump_triples: str | None = None) -> None:
    """Ingest a codebase into the local code knowledge graph.

    Phase 1: Walk the repo and write the Project → Folder → File skeleton.
    Phase 2: Parse every source file with tree-sitter into CodeTriples.
    Phase 3: Normalize entity names via Haiku (only if --normalize is passed).
    Phase 4: Write all triples to the local graph.json.
    """
    import json

    repo_path = os.path.abspath(repo_path)
    project_name = os.path.basename(repo_path)
    console.print(f"[bold blue]Ingesting codebase:[/] {repo_path}")

    if not os.path.exists(os.path.join(repo_path, ".codecompass")):
        console.print("[yellow]No .codecompass folder found — running init first...[/]")
        init_project(repo_path)

    client = get_client(repo_path)

    # Preserve agent-authored data (add_entity/add_call, enrich --apply) across
    # the rebuild — graph.clear() would otherwise wipe it every re-ingest.
    # - descriptions: parser-backed nodes described via enrich; mapped onto the
    #   same id in the new graph. An id the parser no longer produces (function
    #   deleted/renamed) is dropped, not resurrected.
    # - created_nodes: wholly agent-created (add_entity) nodes, re-added unless
    #   their file no longer exists.
    descriptions = {nid: a["description"]
                    for nid, a in client.graph.nodes(data=True)
                    if a.get("agent_inferred") and a.get("description")}
    created_nodes = {nid: dict(a) for nid, a in client.graph.nodes(data=True)
                     if a.get("agent_created")}
    agent_edges = [(u, v, dict(e)) for u, v, e in client.graph.edges(data=True)
                   if e.get("agent_inferred")]
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

    # Restore agent-authored data onto the new graph.
    for nid, desc in descriptions.items():
        if nid in client.graph:  # gone from source = dropped, not resurrected
            client.graph.nodes[nid]["description"] = desc
            client.graph.nodes[nid]["agent_inferred"] = True
    for nid, attr in created_nodes.items():
        if nid in client.graph:  # parser now produces it — carry the description
            if attr.get("description"):
                client.graph.nodes[nid]["description"] = attr["description"]
                client.graph.nodes[nid]["agent_inferred"] = True
        elif not attr.get("file") or os.path.exists(os.path.join(repo_path, attr["file"])):
            client.graph.add_node(nid, **attr)  # still missed by the parser
    for u, v, e in agent_edges:  # edges to dropped nodes die with them
        if u in client.graph and v in client.graph:
            client.graph.add_edge(u, v, **e)
    if descriptions or created_nodes or agent_edges:
        client.save()

    total_nodes = client.node_count()
    client.close()

    # Phase 5 — rebuild the vector index from the final graph (parser nodes
    # plus restored agent-inferred ones). Wipes and rewrites like the graph.
    try:
        from graph.vector_store import index_entities
        n = index_entities(repo_path)
        console.print(f"[dim]Phase 5/5 — Vector index rebuilt ({n} entities embedded)[/]")
    except Exception as exc:
        console.print(f"[dim]Phase 5/5 — Vector index skipped ({exc})[/]")

    console.print(
        f"[bold green]Done.[/] Wrote {written} triples. "
        f"Graph now has {total_nodes} nodes."
    )
    console.print(
        "[dim]Next: record anything the parser missed — `add_entity` for "
        "entities, `add_call` for call edges. Agent-recorded data survives "
        "re-ingest.[/]"
    )
    _register_project_agents_md(repo_path)


def _register_project_agents_md(repo_path: str) -> None:
    """Write or update the Code graph section in the project's AGENTS.md."""
    block = f"""{_CODECOMPASS_START}
## Code graph

**{_CODECOMPASS_READ_INSTRUCTION}**

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

### The graph improves with use — record what it missed

While reading code you may find entities, calls, or important variables the
parser didn't capture. Record them immediately with the MCP tools
`add_entity(name, kind, file, line, description)` and
`add_call(caller, callee, line)`. Both mark entries `agent_inferred` and skip
anything ambiguous rather than guess. Small opportunistic writes keep the
graph accurate between full `enrich` runs.

### Enrichment — user-triggered ONLY

The `enrich` tool stages entities for an agent swarm to fill in one-line
descriptions and missing call edges (see `.codecompass/enrich/INSTRUCTIONS.md`
when staged; merge with `enrich(apply=True)`). This is expensive and
**must only run when the user explicitly asks** for enrichment (e.g. "enrich
the graph", "add descriptions", "fill in missing calls").

**Do NOT run `enrich` automatically** after re-ingesting, editing files, or
any other routine step — routine re-ingestion is the `ingest` tool.
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

    p_enrich = subparsers.add_parser(
        "enrich", help="Agent swarm fills descriptions + missing call edges")
    p_enrich.add_argument("repo_path", nargs="?", default=".")
    p_enrich.add_argument("--batch-size", type=int, default=15)
    p_enrich.add_argument("--force", action="store_true")
    p_enrich.add_argument("--apply", action="store_true")

    p_load = subparsers.add_parser("load-triples", help="Load pre-normalized triples into the graph")
    p_load.add_argument("triples_file")
    p_load.add_argument("repo_path")

    p_watch = subparsers.add_parser("watch", help="Watch a repo and keep the graph updated")
    p_watch.add_argument("repo_path", nargs="?", default=".")

    p_mcp = subparsers.add_parser("mcp", help="Run the MCP server")
    p_mcp.add_argument("repo_path", nargs="?", default=".")

    p_setup_pi = subparsers.add_parser(
        "setup-pi", help="Wire CodeCompass into pi (skill + pi-mcp-adapter + mcp.json)")
    p_setup_pi.add_argument("--force", action="store_true",
                            help="Re-copy skill and config even if already set up")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "setup-pi":
        from pi_setup import setup_pi
        setup_pi(force=args.force)
        return

    from pi_setup import auto_setup_pi
    auto_setup_pi()

    if args.command == "enrich":
        if args.apply:
            from ingestion.enricher import apply_enrich_results
            stats = apply_enrich_results(args.repo_path)
            console.print(
                f"[bold green]Applied[/] {stats['descriptions']} descriptions, "
                f"added {stats['edges_added']} call edges "
                f"({stats['calls_skipped']} ambiguous calls skipped)."
            )
        else:
            from ingestion.enricher import prepare_enrich_batches
            staged = prepare_enrich_batches(
                args.repo_path, batch_size=args.batch_size, force=args.force
            )
            if staged["num_entities"] == 0:
                console.print("[dim]Nothing to enrich.[/]")
            else:
                console.print(
                    f"[bold green]Staged[/] {staged['num_entities']} entities in "
                    f"{staged['num_batches']} batch(es) at {staged['enrich_dir']}.\n"
                    f"Read {staged['instructions_path']} and dispatch a sub-agent per "
                    f"batch, then run `codecompass enrich {args.repo_path} --apply`."
                )

    elif args.command == "load-triples":
        load_triples(args.triples_file, args.repo_path)

    elif args.command == "watch":
        watch_code(args.repo_path)

    elif args.command == "mcp":
        if args.repo_path != ".":
            os.environ["CODECOMPASS_REPO"] = os.path.abspath(args.repo_path)
        from mcp_server import main as mcp_main
        mcp_main()


if __name__ == "__main__":
    main()
