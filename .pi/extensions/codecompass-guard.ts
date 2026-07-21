// Installed by `codecompass init` into .pi/extensions/.
// Blocks raw text search (grep/rg) and whole-file dumps (cat) so discovery
// routes through the codecompass graph. Loads only in this trusted project.
// Safe to edit — init only writes this file if it does not already exist.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BLOCKED_SHELL_RE = /(?:^|[;|&])\s*(grep|rg|cat)(?:\s|$)/;

const REASON =
  "Don't grep/cat/rg the repo. Discover through the codecompass graph — " +
  "`codecompass query --grep <pattern>` to find what's relevant, then " +
  "--flow/--impact/--deps to trace — then read the specific slice with the " +
  "Read tool (or sed -n/head/tail), not a whole-file dump.";

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
