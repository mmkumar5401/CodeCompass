#!/usr/bin/env python3
"""PreToolUse hook: block code *search* and whole-file dumps; allow targeted reads.

Discovery must go through the graph — `codecompass query --map`/`--search` to
find what's relevant, then `--flow`/`--impact`/`--deps` to trace it — so raw text
search (grep/rg and the Grep/Glob tools) is blocked. Whole-file `cat` is blocked
too: read targeted slices with the Read tool (or `sed -n`/`head`/`tail`) once you
know what to open, rather than dumping an entire file.
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
