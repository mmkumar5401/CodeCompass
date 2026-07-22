"""CodeCompass — code dependency index for LLM coding agents.

Commands:
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
    (".codecompass/vectors.lance/", "# CodeCompass vector index (rebuilt on ingest)"),
    (".codecompass/graph.json.copy", "# CodeCompass half-built graph from an interrupted ingest"),
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
# (?![\w-]) keeps the bare-`cat` rule off hyphenated names; git's own
# subcommands are matched by the `\bgit\b ...` alternatives below.
_BLOCKED_SHELL_RE = re.compile(
    r"\b(?:grep|rg|cat)\b(?![\w-])"
    # git's own search/dump: `git grep`, `git log -S/-G`, `git ls-files`, `git cat-file`
    r"|\bgit\b[^|;&]*?\s(?:grep|ls-files|cat-file)\b"
    r"|\bgit\b[^|;&]*?\slog\b[^|;&]*?\s-[SG]"
)


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
                    _block("grep/rg/cat/git grep")
            if not saw_path:  # unparseable — decide by where the agent stands
                repo = _repo_containing(os.path.realpath(cwd))
                if repo:
                    _block("grep/rg/cat/git grep")
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
// git's own search/dump is blocked too: `git grep`, `git log -S/-G`, `git ls-files`, `git cat-file`.
const BLOCKED_SHELL_RE =
  /\b(?:grep|rg|cat)\b(?![\w-])|\bgit\b[^|;&]*?\s(?:grep|ls-files|cat-file)\b|\bgit\b[^|;&]*?\slog\b[^|;&]*?\s-[SG]/;

const REASON =
  "Don't grep/cat/rg (or `git grep`) the repo. Discover through the codecompass MCP tools — " +
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


def ingest_code(repo_path: str, normalize: bool = False, dump_triples: str | None = None,
                on_progress=None) -> None:
    """Ingest a codebase into the local code knowledge graph.

    Phase 1: Walk the repo and write the Project → Folder → File skeleton.
    Phase 2: Parse every source file with tree-sitter into CodeTriples.
    Phase 3: Normalize entity names via Haiku (only if --normalize is passed).
    Phase 4: Write all triples to the local graph.json.

    on_progress: called as on_progress(percent, message) — for callers with no
    console (the MCP server). Percent is 0-100 across all phases.
    """
    import json

    def _report(pct: int, message: str) -> None:
        if on_progress:
            on_progress(pct, message)

    repo_path = os.path.abspath(repo_path)
    project_name = os.path.basename(repo_path)
    console.print(f"[bold blue]Ingesting codebase:[/] {repo_path}")

    if not os.path.exists(os.path.join(repo_path, ".codecompass")):
        console.print("[yellow]No .codecompass folder found — running init first...[/]")
        init_project(repo_path)

    # Build into graph.json.copy and swap it in at the end, so a crashed or
    # interrupted ingest leaves the previous graph intact instead of a cleared
    # one. Everything agent-written — nodes, edges, descriptions — is read off
    # the OLD graph now and joined onto the new one once it exists; whatever the
    # parser no longer produces is dropped in that join.
    previous = get_client(repo_path)
    previous_nodes = {nid: dict(a) for nid, a in previous.graph.nodes(data=True)}
    agent_edges = [(u, v, dict(e)) for u, v, e in previous.graph.edges(data=True)
                   if e.get("agent_inferred")]
    del previous  # never saved — the old file stays untouched until the swap

    client = get_client(repo_path, "graph.json.copy")
    client.graph.clear()  # a stale copy from an interrupted run
    client.sync_descriptions = False  # sidecar is written once, at the join

    console.print("[dim]Phase 1/4 — Building hierarchy…[/]")
    _report(2, "Building hierarchy…")
    file_id_map = build_hierarchy(repo_path, project_name, client)
    console.print(f"[dim]  {len(file_id_map)} source files indexed[/]")

    console.print("[dim]Phase 2/4 — Parsing source files…[/]")
    # Parsing dominates the wall clock, so it owns 5-70% of the bar.
    _report(5, f"Parsing {len(file_id_map)} source files…")
    last_pct = 5

    def _parsed(done: int, total: int) -> None:
        nonlocal last_pct
        pct = 5 + int(65 * done / max(total, 1))
        if pct > last_pct:  # one notification per percent, not per file
            last_pct = pct
            _report(pct, f"Parsing files ({done}/{total})…")

    raw_triples = parse_directory(repo_path, progress=True,
                                  on_progress=_parsed if on_progress else None)
    console.print(f"[dim]  {len(raw_triples)} raw triples extracted[/]")

    def _abandon() -> None:
        """Walk away from the half-built copy, leaving the live graph alone."""
        if os.path.exists(client.storage_path):
            os.remove(client.storage_path)

    if not raw_triples:
        console.print("[yellow]No triples extracted — check that the repo contains supported files.[/]")
        _abandon()
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
        _abandon()
        console.print(f"[bold green]Dumped {len(raw_triples)} raw triples to:[/] {dump_triples}")
        return

    if normalize:
        from ingestion.code_normalizer import normalize_triples
        console.print("[dim]Phase 3/4 — Normalizing triples via Haiku…[/]")
        _report(72, "Normalizing triples via Haiku…")
        triples = normalize_triples(raw_triples, progress=True)
        console.print(f"[dim]  {len(triples)} triples after normalization[/]")
    else:
        console.print("[dim]Phase 3/4 — Skipping normalization (pass --normalize to enable)[/]")
        triples = raw_triples

    console.print("[dim]Phase 4/4 — Writing to local graph…[/]")
    _report(85, f"Writing {len(triples)} triples to the graph…")
    written = client.write_code_triples_batch(triples, file_id_map, project_name)

    # Join the old graph onto the fresh one, matching by node id. The parse is
    # the authority on parser-visible code: a node it no longer produces was
    # deleted or renamed in source, and is dropped here rather than lingering as
    # a ghost. Two things outlive that rule — attributes on a surviving node,
    # and entities/edges the agent recorded because the parser never saw them.
    for nid, attr in previous_nodes.items():
        node = client.graph.nodes.get(nid)
        if node is not None:
            for key, value in attr.items():
                node.setdefault(key, value)  # fresh parser values always win
        elif attr.get("agent_created") and (
                not attr.get("file")
                or os.path.exists(os.path.join(repo_path, attr["file"]))):
            # The parser still can't see it (dynamic registration, a construct
            # tree-sitter misses), so the agent's node is all there is. It lives
            # while its file does; a file-less external module always survives.
            client.graph.add_node(nid, **attr)
    for u, v, e in agent_edges:  # edges to dropped nodes die with them
        if u in client.graph and v in client.graph:
            client.graph.add_edge(u, v, **e)
    dropped = client.prune_descriptions()

    # Swap the copy in. os.replace is atomic, so a reader sees either the old
    # graph or the new one, never a truncated file.
    client.sync_descriptions = True  # the one sidecar write of the whole ingest
    client.save()
    final_path = os.path.join(repo_path, ".codecompass", "graph.json")
    os.replace(client.storage_path, final_path)
    client.storage_path = final_path

    if dropped:
        console.print(f"[dim]  {dropped} description(s) dropped — node gone from source[/]")

    total_nodes = client.node_count()
    client.close()

    # Phase 5 — rebuild the vector index from the final graph (parser nodes
    # plus restored agent-inferred ones). Wipes and rewrites like the graph.
    try:
        from graph.vector_store import index_entities
        _report(95, "Rebuilding vector index…")
        n = index_entities(repo_path)
        console.print(f"[dim]Phase 5/5 — Vector index rebuilt ({n} entities embedded)[/]")
    except Exception as exc:
        console.print(f"[dim]Phase 5/5 — Vector index skipped ({exc})[/]")

    _report(100, f"Done — {written} triples, {total_nodes} nodes.")
    console.print(
        f"[bold green]Done.[/] Wrote {written} triples. "
        f"Graph now has {total_nodes} nodes."
    )
    console.print(
        "[dim]Next: add anything that would make the graph more helpful — "
        "`add_entity` (entities, descriptions), `add_call` (calls, imports, "
        "inheritance) — then update .codecompass/overview.md, memory.md, and "
        "learnings.md.[/]"
    )
    _register_project_agents_md(repo_path)


def _register_project_agents_md(repo_path: str) -> None:
    """Write or update the Code graph section in the project's AGENTS.md."""
    block = f"""{_CODECOMPASS_START}
## Code graph

**{_CODECOMPASS_READ_INSTRUCTION}**

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
| `.codecompass/description.jsonl` | one `{{"node": "<node id>", "description": "..."}}` per line — the sole home of descriptions, joined onto results by node id at read time | you, via `add_entity`. Survives the rebuild (and a deleted `graph.json`) because the parser never writes it. Entries whose node the new parse doesn't contain are pruned |
| `.codecompass/vectors.lance/` | embedded `kind + name + file + description` per entity, for `search` | rebuilt from the graph + descriptions at the end of every `ingest`. **It is a snapshot**: descriptions you add now are not searchable until the next `ingest` |
| `.codecompass/overview.md`, `memory.md`, `learnings.md` | prose context (see Priority 1) | you |

### The MCP tools

Every read tool takes an optional `hops` (default 3) where a traversal depth
makes sense, and returns a `description` on each entity row.

**Discover — you don't know the symbol yet**

| Tool | In | Out | Use when |
|---|---|---|---|
| `grep` | `pattern` (Python regex), `field` (`all`\\|`name`\\|`file`\\|`kind`\\|`description`), `ignore_case`, `limit` | matching entities: `name`, `kind`, `file`, `line`, `description`, `matched_field`, `match` | you have a name, a pattern, or a word you expect in a description (`^test_`, `.*Adapter$`, `handle\\|dispatch`) |
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
| `flow_summary` | `entry_symbol`, `hops`, `format` (`mermaid`\\|`json`\\|`drawio`) | the trace plus rendered content; `json` embeds each function's signature, docstring, and source | explaining a pipeline to a human. Use `format="json"` and narrate from the entry point down — never guess a flow from file names |
| `styles` | `element` | CSS selectors that style it: `selector`, `source_file`, `line` | front-end work |
| `dead_code` | `include_entrypoints` | `dead` + `maybe_entrypoint` candidates | hunting unused code. STATIC only — verify each before deleting |

**Write — you learned something (see Priority 0)**

| Tool | In | Out |
|---|---|---|
| `add_entity` | `name`, `kind`, `file`, `line`, `description`, `language` | `created`/`updated` + node id. Description goes to `description.jsonl`; language is inferred from the extension |
| `add_call` | `caller`, `callee`, `line`, `relation` (`CALLS`\\|`IMPORTS`\\|`INHERITS`) | `added`/`exists`/`skipped` (+ reason). Structural edges are parser-owned and refused |

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

    if args.command == "load-triples":
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
