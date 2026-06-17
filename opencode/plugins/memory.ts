/**
 * CodeCompass Session Memory Plugin for opencode.
 *
 * Replaces the old Claude Code hooks (SessionStart, PreCompact, Stop, PostToolUse)
 * with opencode-native equivalents.
 *
 * Hooks:
 *   experimental.session.compacting — injects context so the LLM preserves
 *     learnings across compaction boundaries
 *   session.idle  — writes lightweight session metadata to memory/session_log.md
 *   session.compacted — triggers learnings summarization to memory/learnings.md
 */

import type { Plugin } from "@opencode-ai/plugin"

const GRAPHRAG_ROOT = "/Users/manojkumarmuthukumaran/Documents/Work/codecompass"
const MEMORY_SCRIPT = `${GRAPHRAG_ROOT}/opencode/scripts/save_learnings.py`
const LOG_SCRIPT = `${GRAPHRAG_ROOT}/opencode/scripts/log_session.py`

export const CodeCompassMemory: Plugin = async ({ $, directory }) => {
  return {
    "experimental.session.compacting": async (_input, output) => {
      output.context.push(`## CodeCompass Session Memory

Before generating the compaction summary, review this conversation and include:

### Key Learnings
- Design decisions made and why
- Problems solved and how
- Constraints discovered
- Patterns established
- Non-obvious insights

### Active Context
- Current task and its status
- Files being modified
- Blockers or dependencies

Format the learnings section so they can be extracted later if needed.`)
    },

    event: async ({ event }) => {
      if (event.type === "session.idle") {
        await $`python ${LOG_SCRIPT} ${directory}`.quiet().nothrow()
      }
      if (event.type === "session.compacted") {
        await $`python ${MEMORY_SCRIPT} ${directory}`.quiet().nothrow()
      }
    },
  }
}
