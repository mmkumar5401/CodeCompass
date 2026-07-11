#!/usr/bin/env python3
"""PreToolUse hook: force codecompass for codebase navigation instead of raw file search."""
import json
import re
import sys

# Only block what codecompass unambiguously replaces: searching/reading code
# content. `ls`/`find` are left alone — they have legitimate non-code uses
# (checking build output, confirming a generated file exists, listing test
# fixtures) that the graph doesn't cover. Read is also left alone: it is the
# terminal step ("find the entity with codecompass, then read it").
_BLOCKED_TOOLS = {"Grep", "Glob"}
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
