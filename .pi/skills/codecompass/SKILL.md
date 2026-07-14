---
name: codecompass
description: Use the CodeCompass graph CLI from pi via bash. Use for discovery, impact/dependency traces, dead-code checks, and flow analysis in any repository that has a .codecompass/graph.json index.
---

# CodeCompass

Pi has no CodeCompass MCP, so run the `codecompass` CLI through the **bash** tool.

Install the CLI if it’s not already available:

```bash
pip install codecompass-mcp
```

## Index / re-index the repo

```bash
codecompass ingest-code
```

Run after any code change to keep `.codecompass/graph.json` current.

## Discovery

```bash
codecompass query --tree                          # full project tree
codecompass query --map                           # compact {file: [symbols]} index
codecompass query --search "session cookie"       # keyword search
codecompass query --grep "^get_"                  # regex over indexed entities
```

## Trace and impact

```bash
codecompass query --impact "login()"              # callers of an entity
codecompass query --blast-radius src/auth.py      # files affected by a change
codecompass query --batch-impact "foo()" "bar()"  # union blast radius for many targets
codecompass query --deps src/auth.py              # imports/dependencies
codecompass query --flow "handle_request()"       # lean flow structure
codecompass query --flow-summary "handle_request()" # mermaid + narration
codecompass query --styles LoginForm              # CSS selectors styling an element
```

## Dead code

```bash
codecompass query --dead-code
codecompass query --dead-code --include-entrypoints
```

## Other commands

```bash
codecompass init <repo_path>                      # create .codecompass/ stubs
codecompass describe                              # stage entity descriptions (user-triggered only)
codecompass watch                                 # keep graph updated as files change
```

## Notes

- All commands default to the current directory. Pass a repo path to run elsewhere.
- `codecompass describe` is expensive and should only run when the user explicitly asks for descriptions.
- If the graph is stale (>24h), re-run `codecompass ingest-code`.
