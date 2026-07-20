import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve, sep } from "node:path";
import { execSync } from "node:child_process";

// This extension is packaged so other repos can `pi install` it instead of
// copying files. The system prompt text lives in templates/APPEND_SYSTEM.md,
// the AGENTS.md template lives in templates/AGENTS.md, and the skill lives in
// templates/skills/codecompass/SKILL.md. Keep APPEND_SYSTEM.md and AGENTS.md
// in sync with the repo's .pi/APPEND_SYSTEM.md and AGENTS.md. A sync check
// script is available at scripts/check-pi-package-sync.sh.
//
// The extension also bootstraps the Python `codecompass-mcp` package via
// `/codecompass-init`, so users do not need to run pip install manually.
const TEMPLATE_DIR = join(__dirname, "..", "templates");

// Search tools/commands and whole-file dumps — blocked. Use the graph to
// discover, then read targeted slices.
const _BLOCKED_SHELL_RE = /(?:^|[;|&]|&&|\|\|)\s*(grep|rg|cat)(?:\s|$)/;

// Registry of codecompass repos — block only reads inside one of them.
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

function commandExists(name: string): boolean {
  try {
    execSync(`command -v ${name}`, { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function detectPackageSource(): string {
  // Try to figure out where this extension was installed from so users don't
  // have to type the package source every time.
  const parts = __dirname.split(/[\\/]/);

  const nodeModulesIdx = parts.lastIndexOf("node_modules");
  if (nodeModulesIdx !== -1 && parts[nodeModulesIdx + 1]) {
    const name = parts[nodeModulesIdx + 1].startsWith("@")
      ? `${parts[nodeModulesIdx + 1]}/${parts[nodeModulesIdx + 2]}`
      : parts[nodeModulesIdx + 1];
    return `npm:${name}`;
  }

  const gitIdx = parts.indexOf("git");
  if (gitIdx !== -1 && parts[gitIdx + 1] && parts[gitIdx + 2] && parts[gitIdx + 3]) {
    return `git:${parts[gitIdx + 1]}/${parts[gitIdx + 2]}/${parts[gitIdx + 3]}`;
  }

  // Fallback for local development or unknown install paths.
  return "npm:codecompass-pi";
}

function loadSystemPrompt(): string {
  return readFileSync(join(TEMPLATE_DIR, "APPEND_SYSTEM.md"), "utf8");
}

export default function (pi: ExtensionAPI) {
  const codecompassPrompt = loadSystemPrompt();

  // Inject the CodeCompass system prompt on every turn.
  pi.on("before_agent_start", async (event) => {
    if (event.systemPrompt.includes("CodeCompass code knowledge graph")) {
      return undefined;
    }
    return { systemPrompt: event.systemPrompt + "\n\n" + codecompassPrompt };
  });

  // Block raw text search and whole-file dumps inside codecompass projects.
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
        const repo = repoContaining(cwd);
        if (repo) return { block: true, reason: blockReason("grep/rg/cat", repo) };
      }
      // every named path is outside all codecompass repos — allow
    }
    return undefined;
  });

  // Notify users if codecompass is not installed yet.
  pi.on("session_start", async (_event, ctx) => {
    if (!commandExists("codecompass")) {
      ctx.ui.notify(
        "CodeCompass CLI not found. Run `/codecompass-init` to install it.",
        "warning",
      );
    }
  });

  // /codecompass-init — mirrors `codecompass init` for Claude Code.
  pi.registerCommand("codecompass-init", {
    description: "Initialize CodeCompass guardrails in the current project",
    handler: async (args, ctx) => {
      const cwd = ctx.cwd;
      const packageSource = args.trim() || detectPackageSource();

      // 1. Ensure codecompass is installed.
      if (!commandExists("codecompass")) {
        ctx.ui.notify("Installing codecompass-mcp via pip...", "info");
        try {
          execSync("pip install codecompass-mcp", { stdio: "pipe" });
          ctx.ui.notify("codecompass-mcp installed.", "info");
        } catch (err) {
          ctx.ui.notify(
            `Failed to install codecompass-mcp: ${err instanceof Error ? err.message : String(err)}`,
            "error",
          );
          return;
        }
      }

      // 2. Copy AGENTS.md template into the project.
      const agentsSrc = join(TEMPLATE_DIR, "AGENTS.md");
      const agentsDst = join(cwd, "AGENTS.md");

      if (!existsSync(agentsSrc)) {
        ctx.ui.notify("Could not find AGENTS.md template in package", "error");
        return;
      }

      if (existsSync(agentsDst)) {
        const ok = await ctx.ui.confirm(
          "AGENTS.md exists",
          "Overwrite existing AGENTS.md with CodeCompass template?",
        );
        if (!ok) return;
      }

      writeFileSync(agentsDst, readFileSync(agentsSrc, "utf8"));

      // 3. Copy the CodeCompass skill into .pi so pi can load it on demand.
      const skillSrc = join(TEMPLATE_DIR, "skills", "codecompass", "SKILL.md");
      const skillDst = join(cwd, ".pi", "skills", "codecompass", "SKILL.md");
      if (existsSync(skillSrc)) {
        mkdirSync(join(cwd, ".pi", "skills", "codecompass"), { recursive: true });
        if (!existsSync(skillDst)) {
          writeFileSync(skillDst, readFileSync(skillSrc, "utf8"));
        }
      }

      // 4. Create .pi/settings.json so the package auto-installs for others.
      const piDir = join(cwd, ".pi");
      const settingsPath = join(piDir, "settings.json");
      let settings: { packages?: string[] } = {};

      if (existsSync(settingsPath)) {
        try {
          settings = JSON.parse(readFileSync(settingsPath, "utf8")) as { packages?: string[] };
        } catch {
          ctx.ui.notify("Existing .pi/settings.json is invalid JSON", "error");
          return;
        }
      } else {
        mkdirSync(piDir, { recursive: true });
      }

      const packages = new Set(settings.packages ?? []);
      packages.add(packageSource);
      settings.packages = [...packages];
      writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + "\n");

      // 5. Ingest the codebase.
      try {
        execSync("codecompass ingest-code", { cwd, stdio: "pipe" });
        ctx.ui.notify("CodeCompass initialized: AGENTS.md, .pi/settings.json, .pi/skills/codecompass, graph ingested.", "info");
      } catch (err) {
        ctx.ui.notify(`Ingest failed: ${err instanceof Error ? err.message : String(err)}`, "error");
      }
    },
  });
}
