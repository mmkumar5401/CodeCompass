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
        repo = _repo_containing(target)
        if repo:
            _block(f"the {tool_name} tool")
        sys.exit(0)  # outside every codecompass repo — no graph to route through

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
