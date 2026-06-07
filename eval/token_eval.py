"""
Token usage evaluation: blind exploration vs graph-guided navigation.

Simulates Claude working on a project WITHOUT the folder mounted —
it cannot read files directly. It must navigate from a project tree.

Blind pipeline (3 steps, simulates exploration overhead):
  1. Claude gets task + project tree → asks which files it needs
  2. We read those files (including any wrong guesses)
  3. Claude gets task + file contents → produces the edit

Guided pipeline (2 steps, graph eliminates exploration):
  1. Graph query → exact files identified instantly
  2. Claude gets task + those files → produces the edit

Total tokens = all steps combined. This shows the real cost of not having
the graph when working outside the mounted project folder.
"""

import subprocess
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

GRAPHRAG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TASKS = [
    {
        "q": "Add a method to build_hierarchy that returns only top-level folder paths.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--deps", "ingestion/hierarchy_builder.py", "--project", "graphrag", "--plain"],
    },
    {
        "q": "Add a new tree-sitter language (Ruby) to the code parser.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--deps", "ingestion/code_parser.py", "--project", "graphrag", "--plain"],
    },
    {
        "q": "Add a retry mechanism to the Neo4j client for transient connection failures.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--deps", "graph/neo4j_client.py", "--project", "graphrag", "--plain"],
    },
    {
        "q": "Add a callback hook to file_watcher that fires when a file is deleted.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--deps", "ingestion/file_watcher.py", "--project", "graphrag", "--plain"],
    },
    {
        "q": "Add a confidence threshold argument to entity_resolver so low-confidence duplicates are skipped.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--impact", "entity_resolver", "--project", "graphrag", "--plain"],
    },
    {
        "q": "Add a timeout parameter to the agentic query agent.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--deps", "query/agentic_agent.py", "--project", "graphrag", "--plain"],
    },
    {
        "q": "Add logging to graph_writer so every triple write is logged with a timestamp.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--deps", "ingestion/graph_writer.py", "--project", "graphrag", "--plain"],
    },
    {
        "q": "Add a --max-results flag to query_cli that limits how many edges are returned.",
        "cmd": ["python", "-m", "graph.code_query_cli", "--deps", "graph/query_cli.py", "--project", "graphrag", "--plain"],
    },
]

APPEND_NAVIGATE = (
    "You are given a project file tree and a task. "
    "List ONLY the file paths you need to read to complete the task. "
    "One path per line, no explanation, no bullet points, just the paths. "
    "Use paths exactly as they appear in the tree."
)
APPEND_EDIT = "You are making an edit to a codebase. Use the file contents provided to give a concise, specific answer. No preamble."
APPEND_GUIDED = "The knowledge graph has identified exactly which files are relevant. Use them to give a concise, specific answer. No preamble."


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total(self):
        return self.input_tokens + self.output_tokens

    def __iadd__(self, other):
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd += other.cost_usd
        return self


@dataclass
class Result:
    task: str
    blind_usage: Usage = None
    guided_usage: Usage = None
    blind_files_read: list = field(default_factory=list)
    guided_files_read: list = field(default_factory=list)
    error: Optional[str] = None

    @property
    def total_delta(self):
        if self.blind_usage and self.guided_usage:
            return self.guided_usage.total - self.blind_usage.total
        return 0


def run_claude(prompt: str, append_system: str) -> tuple[Usage, str]:
    """Returns (usage, response_text)."""
    result = subprocess.run(
        ["claude", "-p", prompt, "--append-system-prompt", append_system, "--output-format", "json"],
        capture_output=True, text=True, cwd=GRAPHRAG_ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"exit {result.returncode}")
    data = json.loads(result.stdout)
    if data.get("is_error"):
        raise RuntimeError(data.get("result", "unknown error"))
    u = data.get("usage", {})
    usage = Usage(
        input_tokens=u.get("input_tokens", 0),
        output_tokens=u.get("output_tokens", 0),
        cost_usd=data.get("total_cost_usd", 0.0),
    )
    return usage, data.get("result", "")


def get_project_tree() -> str:
    result = subprocess.run(
        ["python", "-m", "graph.code_query_cli", "--tree", "graphrag", "--plain"],
        capture_output=True, text=True, cwd=GRAPHRAG_ROOT,
    )
    return result.stdout.strip()


def query_graph(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=GRAPHRAG_ROOT)
    return result.stdout.strip()


def parse_file_paths(text: str) -> list[str]:
    """Extract file paths from Claude's navigation response."""
    paths = []
    for line in text.strip().splitlines():
        line = line.strip().strip("-").strip("*").strip()
        # keep lines that look like relative file paths
        if "/" in line and not line.startswith("#") and len(line) < 80:
            # strip any inline commentary after a space
            path = line.split()[0]
            if any(path.endswith(ext) for ext in [".py", ".json", ".md", ".txt", ".yaml", ".yml"]):
                paths.append(path)
    return paths


def read_files(file_paths: list[str]) -> str:
    parts = []
    for path in file_paths:
        full = os.path.join(GRAPHRAG_ROOT, path)
        try:
            with open(full) as f:
                content = f.read()
            parts.append(f"# {path}\n```python\n{content}\n```")
        except FileNotFoundError:
            parts.append(f"# {path}\n(file not found)")
    return "\n\n".join(parts)


def evaluate(project_tree: str) -> list[Result]:
    results = []

    for i, task in enumerate(TASKS, 1):
        question = task["q"]
        console.print(f"\n[bold cyan][{i}/{len(TASKS)}][/] {question}")
        r = Result(task=question)

        # ── BLIND pipeline ──────────────────────────────────────────────────
        # Step 1: Claude sees tree + task → decides which files to read
        nav_prompt = (
            f"Project file tree:\n{project_tree}\n\n"
            f"Task: {question}\n\n"
            f"Which files do you need to read?"
        )
        console.print("  [dim]blind step 1 — navigation...[/]", end=" ")
        try:
            nav_usage, nav_response = run_claude(nav_prompt, APPEND_NAVIGATE)
            identified = parse_file_paths(nav_response)
            console.print(f"[yellow]{nav_usage.total} tokens[/] → identified: {identified}")
        except Exception as e:
            r.error = str(e)
            console.print(f"[red]{e}[/]")
            results.append(r)
            continue

        time.sleep(1)

        # Step 2: Read those files, ask Claude to do the task
        file_contents = read_files(identified) if identified else "(no files identified)"
        r.blind_files_read = identified
        edit_prompt = f"Files:\n\n{file_contents}\n\nTask: {question}"

        console.print(f"  [dim]blind step 2 — edit ({len(identified)} files)...[/]", end=" ")
        try:
            edit_usage, _ = run_claude(edit_prompt, APPEND_EDIT)
            r.blind_usage = nav_usage
            r.blind_usage += edit_usage
            console.print(f"[green]{edit_usage.total} tokens[/] | total blind: [bold]{r.blind_usage.total}[/] (${r.blind_usage.cost_usd:.4f})")
        except Exception as e:
            r.error = str(e)
            console.print(f"[red]{e}[/]")
            results.append(r)
            continue

        time.sleep(1)

        # ── GUIDED pipeline ─────────────────────────────────────────────────
        # Step 1: Graph query → exact files
        graph_context = query_graph(task["cmd"])

        # parse file paths out of graph output
        guided_files = []
        for line in graph_context.splitlines():
            # deps output: "  models.code_types (module) [depth 2]"
            # convert module notation to file path where possible
            match = re.match(r"\s+([\w.]+)\s+\(module\)", line)
            if match:
                mod = match.group(1)
                # only include project-internal modules (no stdlib/third-party)
                if not any(mod.startswith(p) for p in ["os", "sys", "re", "json", "uuid",
                    "pathlib", "typing", "datetime", "dataclasses", "asyncio",
                    "anthropic", "neo4j", "rich", "tqdm", "dotenv", "tree_sitter",
                    "watchdog", "PyPDF2", "pytest", "subprocess", "argparse"]):
                    file_path = mod.replace(".", "/") + ".py"
                    if os.path.exists(os.path.join(GRAPHRAG_ROOT, file_path)):
                        guided_files.append(file_path)

        if not guided_files:
            # fallback: try to infer from the cmd itself
            for arg in task["cmd"]:
                if arg.endswith(".py") and "/" in arg:
                    if os.path.exists(os.path.join(GRAPHRAG_ROOT, arg)):
                        guided_files.append(arg)

        r.guided_files_read = guided_files
        guided_contents = read_files(guided_files)
        guided_prompt = (
            f"Knowledge graph context:\n{graph_context}\n\n"
            f"Relevant files (identified by graph):\n\n{guided_contents}\n\n"
            f"Task: {question}"
        )

        saved = len(r.blind_files_read) - len(guided_files)
        console.print(f"  [dim]guided — graph + {len(guided_files)} files ({saved:+d} vs blind)...[/]", end=" ")
        try:
            r.guided_usage, _ = run_claude(guided_prompt, APPEND_GUIDED)
            console.print(f"[green]{r.guided_usage.total} tokens[/] (${r.guided_usage.cost_usd:.4f})")
        except Exception as e:
            r.error = str(e)
            console.print(f"[red]{e}[/]")

        results.append(r)
        time.sleep(1)

    return results


def print_report(results: list[Result]):
    console.print("\n")

    t = Table(title="Blind Exploration vs Graph-Guided Navigation (no folder mount)", box=box.ROUNDED)
    t.add_column("#", style="dim", width=3)
    t.add_column("Task", max_width=32)
    t.add_column("Blind\nsteps", justify="right")
    t.add_column("Guided\nsteps", justify="right")
    t.add_column("Blind\ntokens", justify="right")
    t.add_column("Guided\ntokens", justify="right")
    t.add_column("Δ tokens", justify="right")
    t.add_column("Cost Δ", justify="right")

    for i, r in enumerate(results, 1):
        if r.error or not r.blind_usage or not r.guided_usage:
            t.add_row(str(i), r.task[:32], "-", "-", "[red]err[/]", "[red]err[/]", "-", "-")
            continue
        delta_col = "green" if r.total_delta < 0 else "red"
        cost_delta = r.guided_usage.cost_usd - r.blind_usage.cost_usd
        cost_col = "green" if cost_delta < 0 else "red"
        t.add_row(
            str(i),
            r.task[:32],
            "2 (nav+edit)",
            "1 (edit)",
            str(r.blind_usage.total),
            str(r.guided_usage.total),
            f"[{delta_col}]{r.total_delta:+d}[/]",
            f"[{cost_col}]{cost_delta:+.4f}[/]",
        )

    console.print(t)

    valid = [r for r in results if r.blind_usage and r.guided_usage and not r.error]
    if not valid:
        console.print("[red]No valid results.[/]")
        return

    total_blind  = sum(r.blind_usage.total for r in valid)
    total_guided = sum(r.guided_usage.total for r in valid)
    total_cost_blind  = sum(r.blind_usage.cost_usd for r in valid)
    total_cost_guided = sum(r.guided_usage.cost_usd for r in valid)
    net = total_guided - total_blind
    net_col = "green" if net < 0 else "red"
    cost_net = total_cost_guided - total_cost_blind
    cost_col = "green" if cost_net < 0 else "red"

    agg = Table(title="Aggregates", box=box.SIMPLE, show_header=False)
    agg.add_column("Metric", style="bold")
    agg.add_column("Value", justify="right")
    agg.add_row("Tasks evaluated", str(len(valid)))
    agg.add_row("Total tokens — blind (nav + edit)", str(total_blind))
    agg.add_row("Total tokens — guided (edit only)", str(total_guided))
    agg.add_row("Net token delta", f"[{net_col}]{net:+d}[/]")
    agg.add_row("Total cost — blind", f"${total_cost_blind:.4f}")
    agg.add_row("Total cost — guided", f"${total_cost_guided:.4f}")
    agg.add_row("Net cost delta", f"[{cost_col}]${cost_net:+.4f}[/]")
    console.print(agg)

    console.print(
        "\n[dim]Blind = 2 LLM calls: (1) navigate the tree to find files, (2) make the edit.\n"
        "Guided = 1 LLM call: graph already knows the files, go straight to the edit.[/]"
    )


if __name__ == "__main__":
    console.print("[bold]GraphRAG Token Evaluation[/] [dim](simulating no folder mount)[/]")
    console.print(f"Tasks: {len(TASKS)}\n")
    project_tree = get_project_tree()
    console.print(f"[dim]Project tree loaded ({len(project_tree)} chars)[/]\n")
    results = evaluate(project_tree)
    print_report(results)
