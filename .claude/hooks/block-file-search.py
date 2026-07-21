#!/usr/bin/env python3
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
_REPO = "/Users/manojkumarmuthukumaran/Documents/Work/codecompass"
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
