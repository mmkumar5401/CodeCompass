import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    // Only block what codecompass unambiguously replaces: searching/reading
    // code content. `find`/`ls` are left alone — they have legitimate non-code
    // uses (checking build output, confirming a generated file exists,
    // listing test fixtures) that the graph doesn't cover.
    if (event.toolName === "grep") {
      return {
        block: true,
        reason:
          "Codebase navigation must use codecompass. Try: codecompass query --tree, --blast-radius, --impact, --flow, or --deps, then read the file directly.",
      };
    }

    if (event.toolName === "bash") {
      const cmd = String((event.input as { command?: string }).command ?? "");
      const blockedShell = /(?:^|[;|&]|&&|\|\|)\s*(cat|grep|rg)(?:\s|$)/.test(cmd);
      if (blockedShell) {
        return {
          block: true,
          reason:
            "Use codecompass to find the entity/file, then `read` it directly, instead of cat/grep/rg. (`find`/`ls` are fine for non-code exploration.)",
        };
      }
    }
  });
}
