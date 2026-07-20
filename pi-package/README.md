# codecompass-pi

CodeCompass cut 66%-82% of token usage on real coding work. It maps your codebase into a queryable graph so your agent orients from a compact index instead of blind grepping and whole-file dumps.

[Pi](https://pi.dev) has no MCP support, so this package wires CodeCompass in the way pi actually works: a guardrail extension plus a **skill** that teaches the agent to drive the `codecompass` CLI over bash.

What it does:
- Appends the CodeCompass system prompt on every turn, so the agent knows the graph exists and prefers it.
- Blocks raw text search (`grep`, `rg`, `cat`) and whole-file dumps **inside codecompass-registered repos** (`~/.codecompass/repos`), so the agent is pushed toward `codecompass query` — reads outside any registered repo pass through.
- Ships a `codecompass` skill (`.pi/skills/codecompass/SKILL.md`) documenting every CLI command the agent can call.
- Provides `/codecompass-init` — a one-shot setup command, the pi equivalent of `codecompass init` for Claude Code.

Requires `codecompass` on `PATH`. `/codecompass-init` installs it automatically via `pip install codecompass-mcp` if missing. Everything is local — the graph is a single JSON file at `.codecompass/graph.json`.

## Quick start

```bash
pi install npm:codecompass-pi
pi                        # start pi in your repo
/codecompass-init         # one-time setup: AGENTS.md, skill, settings.json, first ingest
```

From then on the agent has the `codecompass` skill available and will reach for `codecompass query` instead of grep/cat.

## CLI commands available to the agent

Once installed, the agent drives CodeCompass entirely through bash — there's no MCP tool surface on pi. These are the commands documented in the shipped skill (`templates/skills/codecompass/SKILL.md`):

```bash
# index / re-index — run after any code change
codecompass ingest-code

# discovery
codecompass query --tree                            # full project tree
codecompass query --grep "^get_"                      # regex over indexed entities

# trace and impact
codecompass query --impact "login()"                  # callers of an entity
codecompass query --blast-radius src/auth.py          # files affected by a change
codecompass query --batch-impact "foo()" "bar()"       # union blast radius for many targets
codecompass query --deps src/auth.py                   # imports/dependencies
codecompass query --flow "handle_request()"            # lean flow structure
codecompass query --flow-summary "handle_request()"    # mermaid + narration
codecompass query --styles LoginForm                    # CSS selectors styling an element

# dead code
codecompass query --dead-code
codecompass query --dead-code --include-entrypoints

# other
codecompass init <repo_path>                            # create .codecompass/ stubs
codecompass enrich                                       # stage descriptions + missing calls for an agent swarm (user-triggered only)
codecompass enrich --apply                                 # merge staged enrich results into the graph
codecompass add-entity <name> --file F --line N --description "..."  # record a parser-missed entity
codecompass add-call <caller> <callee> --line N              # record a parser-missed call edge
codecompass watch                                        # keep graph updated as files change
```

All commands default to the current directory; pass a repo path to run elsewhere. `codecompass enrich` is expensive — only run it when the user explicitly asks. Re-run `codecompass ingest-code` if the graph is stale (>24h).

## Keeping templates in sync

The package ships copies of the guardrail files in `templates/`:

- `templates/APPEND_SYSTEM.md` mirrors `.pi/APPEND_SYSTEM.md`
- `templates/AGENTS.md` mirrors `AGENTS.md`

These must stay byte-for-byte identical to the repo's source files. A sync check is provided:

```bash
./scripts/check-pi-package-sync.sh
```

If it reports a mismatch, copy the updated source file into `templates/`:

```bash
cp .pi/APPEND_SYSTEM.md pi-package/templates/APPEND_SYSTEM.md
cp AGENTS.md pi-package/templates/AGENTS.md
```

## Install the CLI

The Pi extension needs the `codecompass` command on `PATH`. Install it first:

```bash
pip install codecompass-mcp
```

`/codecompass-init` will install it automatically if it is missing, but installing it yourself avoids the first-run pip prompt.

## Install the package

Published to npm as `codecompass-pi`:

```bash
pi install npm:codecompass-pi
```

Local install during development:

```bash
pi install /absolute/path/to/pi-package
```

### Publishing

The package is published automatically via GitHub Actions when a `v*.*.*` tag is pushed, but only if the `NPM_TOKEN` repository secret is configured. Add the secret first — otherwise the publish job will fail.

## Initialize a project

Inside any repo, run:

```bash
/codecompass-init
```

This will:
1. Install `codecompass-mcp` via pip if it is missing.
2. Copy `AGENTS.md` into the project.
3. Create `.pi/skills/codecompass/SKILL.md` so pi can load the CodeCompass skill on demand.
4. Create/update `.pi/settings.json` so the package auto-installs for anyone else who opens the repo with pi.
5. Run `codecompass ingest-code`.

The package source is auto-detected from where the extension was installed. Pass it explicitly only if you installed from a local path or want a different source:

```bash
/codecompass-init git:github.com/<user>/codecompass
```

## Automatic setup for new team members

After `/codecompass-init`, the repo contains `.pi/settings.json` referencing the package. When another developer runs `pi` in that repo and trusts the project, pi automatically installs the package and the guardrails take effect immediately.
