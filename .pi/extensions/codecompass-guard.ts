import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Block code *search* and whole-file dumps; allow targeted reads. Discovery must
// go through the graph (--map / --search to find what's relevant, then
// --flow/--impact/--deps to trace), so raw text search (grep/rg and the grep
// tool) is blocked, and so is whole-file `cat`. Read targeted slices with the
// read tool (or sed -n/head/tail) once you know what to open.
const REASON =
  "Don't grep/rg or cat. Discover through the graph — `codecompass query --map` " +
  "(compact index to reason over) or `--search <kw>`, then `--flow`/`--impact`/`--deps` " +
  "to trace — then read the specific slice you need (read tool or sed -n/head/tail), " +
  "not a whole-file dump.";

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    const isGrepTool = event.toolName === "grep";
    const isBlockedBash =
      event.toolName === "bash" &&
      /(?:^|[;|&]|&&|\|\|)\s*(grep|rg|cat)(?:\s|$)/.test(
        String((event.input as { command?: string }).command ?? ""),
      );

    if (isGrepTool || isBlockedBash) {
      return { block: true, reason: REASON };
    }
  });
}
