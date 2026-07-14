# codecompass-pi

CodeCompass cut 66%-82% of token usage on real coding work. And used to map your codebase and reduce the amount of code your agent reads and opens.

This package adds Pi guardrails and a one-shot `/codecompass-init` command on top of the `codecompass` CLI.

What it does:
- Appends the CodeCompass system prompt on every turn.
- Blocks raw text search (`grep`, `rg`, `cat`) so the agent uses the graph instead.
- Provides `/codecompass-init` to set up a project the same way `codecompass init` does for Claude Code.

Requires `codecompass` to be available on `PATH`. The `/codecompass-init` command installs it automatically via `pip install codecompass-mcp` if it is missing. Neo4j is optional; the local JSON graph at `.codecompass/graph.json` is sufficient for pi.

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
