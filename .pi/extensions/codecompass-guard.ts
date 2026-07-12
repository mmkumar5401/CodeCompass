import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Search tools/commands and whole-file dumps — blocked. Use the graph to
// discover, then read targeted slices.
const _BLOCKED_TOOLS = new Set(["grep"]);
const _BLOCKED_SHELL_RE = /(?:^|[;|&]|&&|\|\|)\s*(grep|rg|cat)(?:\s|$)/;

const _REASON =
  "Don't use {what}. Discover through the graph — `codecompass query --map` " +
  "(compact index to reason over) or `--search <kw>`, then `--flow`/`--impact`/" +
  "`--deps` to trace — then read the specific slice you need with the Read tool " +
  "(or `sed -n`/`head`/`tail`), not a whole-file dump.";

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    const toolName = event.toolName;

    if (_BLOCKED_TOOLS.has(toolName)) {
      return { block: true, reason: _REASON.replace("{what}", `the ${toolName} tool`) };
    }

    if (toolName === "bash") {
      const command = String((event.input as { command?: string }).command ?? "");
      if (_BLOCKED_SHELL_RE.test(command)) {
        return { block: true, reason: _REASON.replace("{what}", "grep/rg/cat") };
      }
    }
  });
}
