
## 2026-06-09

- `python main.py resolve` uses Haiku via the ANTHROPIC_API_KEY — fails with "credit balance too low" if no API credits. `claude -p` subprocess has the same problem: it also hits the API key, not the Claude.ai subscription used by interactive Claude Code sessions.
- Native resolve implemented as a two-phase CLI: `resolve --native --dump <nodes.json>` writes nodes; Claude Code analyzes interactively; `resolve --native --apply <groups.json>` merges. This keeps all LLM work inside the subscription-billed session.
- Ghost nodes (type=NULL) can accumulate in the doc graph after merge operations. They use the `DocEntity` label, not `Entity` — cleanup queries must target `(:DocEntity)`.
- Frontend Nx monorepo (`TM_Repos/frontend`) ingested into code graph under project name `frontend`: 3,006 files, 46,588 triples after dropping 13,402 noise triples (jest assertions, JS built-in methods). Normalization done natively by Claude Code via `--dump-triples` + `load-triples` workflow.
- `learnings.md` was documented in `graphrag/CLAUDE.md` but missing from `~/.claude/CLAUDE.md` and the auto-memory `MEMORY.md` index — now added to both.

## 2026-06-08 (session close)

- PreCompact hook (`scripts/on_compact.py`) is now wired in `.claude/settings.json` — outputs `hookSpecificOutput.additionalContext` to instruct Claude to write learnings before compaction. Zero API cost; Claude writes the file natively during the compaction process.
- Two-path learning design is final: Stop hook → lightweight `session_log.md` metadata only; learnings go to `learnings.md` via "store my session" (user-triggered) or PreCompact hook (automatic on compaction).
- README.md, ONBOARDING.md, and PITCH.md were all corrected this session — they previously described a non-existent LLM-powered Stop hook. Now accurately reflect the two-path design.
- PreCompact `additionalContext` is injected as a system message before the compaction summary is generated — this is the mechanism that lets Claude write to disk during compaction without any API call.
- `on_compact.py` also logs compact events directly to `session_log.md` (timestamp, session ID, git-diff file list) as a fallback — so even if Claude doesn't write learnings, the compact event is recorded.

## 2026-06-08

- Stop hook using `claude -p` is unreliable — too slow (10–30s), gets killed when session closes. Direct Anthropic API call is faster but requires credits. Final decision: Stop hook does lightweight logging only; learnings extraction is user-triggered via "store my session".
- `memory/session_log.md` records automatic lightweight metadata on every session close (timestamp, session ID, files changed via `git diff`). `memory/learnings.md` is written manually on user request.
- The "store my session" trigger is defined in CLAUDE.md — Claude handles extraction natively with no API cost, no subprocess, no timing issues.
- Hooks don't inherit nvm PATH — any script that shells out to `claude` or node-based tools needs the full binary path.
- `async: true` on a Stop hook lets the session close while the hook runs, but slow subprocess calls (like `claude -p`) still get killed before completing.
- SessionStart hook outputs `hookSpecificOutput.hookEventName: "SessionStart"` + `additionalContext` — this is how memory files are injected before the first user message.
- The Stop hook transcript search now uses `rglob` across all `~/.claude/projects/*/` dirs — works regardless of which directory Claude was opened from.
- `auto_bridge.py` (doc-to-code bridging) was built but not wired — had same subprocess stdin issue as auto_memory.py. Needs revisiting with the lightweight approach.
- README, PITCH.md, and ONBOARDING.md added this session — repo is now self-documenting for new users and Claude Code onboarding.

## 2026-06-08 — Claude Code + Codex CLI planner

- `claude -p "<prompt>" --dangerously-skip-permissions` is the correct flag for non-interactive Claude Code output from a subprocess.
- `codex exec --skip-git-repo-check "<prompt>"` is the correct non-interactive Codex CLI invocation — `--skip-git-repo-check` is required when running outside a git repo; passing `input=""` to subprocess closes stdin so it doesn't hang.
- Codex CLI responds with the final answer on the last non-empty line of stdout — strip and split on newlines to extract it.
- Codex CLI supports both ChatGPT sign-in and API-key auth. Model selection works via `~/.codex/config.toml` (`model = "gpt-5.5"`) or the `-m` flag (`codex -m gpt-5.5`). Current recommended models per docs are `gpt-5.5` and `gpt-5.4-mini`. The 400 error seen with `o4-mini` was specific to that model + ChatGPT account combo, not a blanket restriction. Codex cloud tasks (vs local CLI) do not support model selection.
- Two-agent planning pattern: shared history string passed as context to each agent; prefix messages with `[Claude]:` / `[Codex]:` so each agent knows who said what. Claude signals completion with `PLAN_COMPLETE` as a stop token.
- `plan-together.py` lives at `/Users/manojkumarmuthukumaran/Documents/Work/plan-together.py` — orchestrates Claude Code and Codex CLI for collaborative planning sessions.

## 2026-06-08 — Agent Collaboration Lab UI

- Built a full local UI for Claude Code + Codex collaboration at `/Users/manojkumarmuthukumaran/Documents/Work/agent-collab/` — Vite + React frontend, Express backend.
- Backend (`server.js`) wraps both CLIs via `execFile` (not `exec`) — safer for prompt strings with special chars; uses `promisify(execFile)`.
- Vite proxy config (`server.proxy: { '/api': 'http://localhost:3001' }`) eliminates CORS issues in dev without modifying the backend.
- `buildPrompt()` flattens OpenAI-style message arrays into a single string for the `claude -p` CLI — CLIs don't accept structured JSON history, so history must be serialized into the prompt text.
- Codex stdout has metadata header lines before the actual answer; extract by taking the last non-empty line of stdout.
- Default Vite `index.css` sets `#root` width to 1126px with `text-align: center` — must override to `width: 100%; height: 100vh` for a full-viewport app layout.
- Two-terminal workflow: `node server.js` (port 3001) + `npm run dev` (port 5173, proxied).

## 2026-06-08 — Agent Collaboration: debate mode

- Changed both agents from fixed roles (architect / implementer) to symmetric planning agents — both tackle the same problem and debate each other.
- Key prompt principle: instruct each agent to "engage directly with what the other just said" — agree/build/challenge/redirect. Without this, agents produce parallel monologues instead of a real debate.
- "Be opinionated. If you think X is wrong, say so and explain why" is the phrase that unlocks actual disagreement rather than polite turn-taking.
- Role labels in the UI should match the prompt intent — changed both to "Planning Agent" so the UI doesn't imply a division of labor that no longer exists.

## 2026-06-08 — Agent Collaboration: bugs and controls

- Bug: Codex responses rendered as empty bubbles because the Express backend received `stdout: ""` when running `codex exec` through Node `execFile`, even though terminal runs printed the answer.
- Fix: `/api/codex` now uses Codex's `--output-last-message <file>` flag and reads the final response from a temp file; stdout parsing remains only as a fallback.
- Decision: for Codex CLI integration from a server process, prefer `--output-last-message` over parsing terminal transcript text, because Codex stdout contains metadata, warning lines, `codex` markers, and repeated answer/token sections.
- Added a Stop Planning control: the frontend uses `AbortController` to cancel the active fetch and calls `POST /api/stop` so the backend terminates active Claude/Codex CLI child processes.
- Backend now wraps CLI calls in a tracked `runCommand()` helper instead of plain promisified `execFile`, allowing `/api/stop` to send `SIGTERM` with a delayed `SIGKILL` fallback.
- Dev-server reminder: the React app belongs on Vite port `5173`; port `3001` is the Express API server and can show an error page if opened directly.
