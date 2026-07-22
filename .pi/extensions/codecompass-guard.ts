// Installed by the codecompass `init` tool into .pi/extensions/.
// Blocks raw text search (grep/rg) and whole-file dumps (cat) so discovery
// routes through the codecompass graph. Loads only in this trusted project.
// Safe to edit — init only rewrites copies that carry this marker.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Word-boundary match anywhere in the command: catches `grep foo`,
// `git grep foo`, `sudo cat f`, `xargs rg` — not just command position.
// (?![\w-]) avoids false positives like `git cat-file`.
// git's own search/dump is blocked too: `git grep`, `git log -S/-G`, `git ls-files`, `git cat-file`.
const BLOCKED_SHELL_RE =
  /\b(?:grep|rg|cat)\b(?![\w-])|\bgit\b[^|;&]*?\s(?:grep|ls-files|cat-file)\b|\bgit\b[^|;&]*?\slog\b[^|;&]*?\s-[SG]/;

const REASON =
  "Don't grep/cat/rg (or `git grep`) the repo. Discover through the codecompass MCP tools — " +
  "`grep` to find what's relevant, then `flow`/`impact`/`deps` to trace — " +
  "then read the specific slice with the Read tool (or sed -n/head/tail), " +
  "not a whole-file dump.";

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    if (event.toolName === "grep") {
      return { block: true, reason: REASON };
    }
    if (event.toolName === "bash") {
      const command = String((event.input as { command?: string }).command ?? "");
      if (BLOCKED_SHELL_RE.test(command)) {
        return { block: true, reason: REASON };
      }
    }
    return undefined;
  });
}
