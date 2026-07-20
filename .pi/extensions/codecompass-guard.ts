import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve, sep } from "node:path";

// Search tools/commands and whole-file dumps — blocked INSIDE codecompass
// projects; reads outside any registered repo are allowed (no graph there).
const _BLOCKED_SHELL_RE = /(?:^|[;|&]|&&|\|\|)\s*(grep|rg|cat)(?:\s|$)/;

const _REGISTRY =
  process.env.CODECOMPASS_REPOS ?? join(homedir(), ".codecompass", "repos");

function repos(): string[] {
  try {
    const list = readFileSync(_REGISTRY, "utf8")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    return list.length ? list : [process.cwd()];
  } catch {
    return [process.cwd()];
  }
}

function repoContaining(p: string): string | undefined {
  return repos().find((r) => p === r || p.startsWith(r + sep));
}

function resolveExisting(tok: string, cwd: string): string | undefined {
  const expanded = tok.startsWith("~") ? join(homedir(), tok.slice(1)) : tok;
  const abs = isAbsolute(expanded) ? expanded : resolve(cwd, expanded);
  return existsSync(abs) ? realpathSync(abs) : undefined;
}

function blockReason(what: string, repo: string): string {
  return `Don't use ${what}. Discover through the graph — \`codecompass query "${repo}" --grep <pattern>\` to find what's relevant, then \`--flow\`/\`--impact\`/\`--deps\` to trace — then read the specific slice you need with the Read tool (or \`sed -n\`/\`head\`/\`tail\`), not a whole-file dump.`;
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    const toolName = event.toolName;
    const cwd = process.cwd();

    if (toolName === "grep") {
      const input = event.input as { path?: string };
      const target = input.path
        ? resolveExisting(input.path, cwd) ?? resolve(cwd, input.path)
        : cwd;
      const repo = repoContaining(target);
      if (repo) return { block: true, reason: blockReason("the grep tool", repo) };
      return undefined; // outside every codecompass repo — allow
    }

    if (toolName === "bash") {
      const command = String((event.input as { command?: string }).command ?? "");
      if (!_BLOCKED_SHELL_RE.test(command)) return undefined;
      let sawPath = false;
      // ponytail: naive whitespace split — quoted paths with spaces don't
      // resolve and fall through to the conservative cwd check.
      for (const tok of command.split(/\s+/)) {
        if (!tok || tok.startsWith("-")) continue;
        const p = resolveExisting(tok, cwd);
        if (!p) continue;
        sawPath = true;
        const repo = repoContaining(p);
        if (repo) return { block: true, reason: blockReason("grep/rg/cat", repo) };
      }
      if (!sawPath) {
        // unparseable — decide by where the agent stands
        const repo = repoContaining(cwd);
        if (repo) return { block: true, reason: blockReason("grep/rg/cat", repo) };
      }
      // every named path is outside all codecompass repos — allow
    }
    return undefined;
  });
}
