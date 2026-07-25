#!/usr/bin/env python3
"""PreToolUse hook: block code search and whole-file dumps where the graph can
answer instead, and allow them where it can't.

Scope is the index, not the repo. A path is blocked only when it is an indexed
file or a directory containing one, read from `.codecompass/files.txt` (written
by ingest). Only parsed languages become File nodes, so a repo's yaml/md/json/
lock files — like anything outside a registered repo, and any repo with no
index yet — pass through untouched: the graph holds nothing about them, so
there is no answer to route the agent to.

Installed by the codecompass `init` tool. Safe to edit — init only rewrites copies it installed.
"""
import json
import os
import re
import sys

# This project's root, baked in at init time — fallback when the global
# registry of codecompass repos is missing.
_REPO = "/Users/manojkumarmuthukumaran/Documents/Work/codecompass"
_REGISTRY = os.environ.get(
    "CODECOMPASS_REPOS", os.path.expanduser("~/.codecompass/repos"))

_BLOCKED_TOOLS = {"grep", "glob"}
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
    """The registered codecompass repo containing path, or None.

    Compared case-insensitively: macOS/Windows filesystems don't distinguish
    case, and hosts pass cwd in whatever case the session was started with,
    so an exact string match can silently miss the repo we're standing in.
    """
    npath = os.path.realpath(path).lower()
    for repo in _repos():
        nrepo = os.path.realpath(repo).lower()
        if npath == nrepo or npath.startswith(nrepo + os.sep):
            return repo
    return None


_INDEX_CACHE = {}


def _index(repo: str) -> set:
    """Relative paths of every file this repo's graph indexed, lowercased.

    Written by ingest as `.codecompass/files.txt`. An empty set means there is
    no index, which the caller treats the same as standing outside a repo.
    """
    if repo not in _INDEX_CACHE:
        try:
            with open(os.path.join(repo, ".codecompass", "files.txt")) as f:
                _INDEX_CACHE[repo] = {line.strip().lower() for line in f if line.strip()}
        except OSError:
            _INDEX_CACHE[repo] = set()
    return _INDEX_CACHE[repo]


def _covers_indexed(path: str) -> bool:
    """True if path is an indexed file, or a directory containing one.

    A file is its own scope, so `cat api/Foo.php` and `grep -r x api/` ask the
    same question: does the graph know anything here? Only parsed languages
    become File nodes, so a repo's yaml/md/json/lock files are absent from the
    index — the graph has no answer to give about them and the tool call is the
    only way to find out, so those are allowed through.
    """
    repo = _repo_containing(path)
    if repo is None:
        return False
    indexed = _index(repo)
    if not indexed:
        return False
    # Both sides lowercased before relpath for the same reason _repo_containing
    # compares that way: realpath doesn't canonicalize case, so a host that
    # passed a differently-cased cwd would otherwise produce `../repo/a.py`
    # and match nothing in the index.
    rel = os.path.relpath(os.path.realpath(path).lower(),
                          os.path.realpath(repo).lower())
    rel = rel.replace(os.sep, "/")
    if rel in (".", ""):
        return True  # the repo root — the whole index sits under it
    if rel in indexed:
        return True
    prefix = rel + "/"
    return any(p.startswith(prefix) for p in indexed)


def _resolve(token: str, cwd: str) -> str:
    p = os.path.expanduser(token)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def _block(what: str) -> None:
    reason = (
        f"Don't use {what}. Discover through the codecompass MCP tools — "
        "`grep` to find what's relevant, then `flow`/`impact`/`deps` to trace — "
        "then read the specific slice you need with the Read tool (or "
        "`sed -n`/`head`/`tail`), not a whole-file dump."
    )
    # One block signal per host: Claude Code blocks on exit code 2 and shows
    # stderr; pi (via pi-hooks) parses the deny JSON from stdout.
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    print(reason, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name", "").lower()  # Claude: Bash/Grep; pi: bash/grep
    tool_input = payload.get("tool_input", {}) or {}
    cwd = payload.get("cwd") or os.getcwd()

    if tool_name in _BLOCKED_TOOLS:
        target = _resolve(tool_input.get("path") or cwd, cwd)
        if _covers_indexed(target):
            _block(f"the {tool_name} tool")
        sys.exit(0)  # nothing indexed here — no graph answer to route through

    if tool_name == "bash":
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
                if _covers_indexed(p):
                    _block("grep/rg/cat/git grep")
            if not saw_path:  # unparseable — decide by where the agent stands
                if _covers_indexed(os.path.realpath(cwd)):
                    _block("grep/rg/cat/git grep")
            # nothing named touches an indexed file — allow

    sys.exit(0)


if __name__ == "__main__":
    main()
