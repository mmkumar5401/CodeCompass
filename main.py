import asyncio
import sys
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import neo4j_config
from graph.neo4j_client import Neo4jClient  # used by ingest
from ingestion.chunker import chunk_pdf, chunk_text
from ingestion.reader_agent import ingest_chunks_parallel
from ingestion.graph_writer import write_triples
from query.agent import run_agent
from query.graph_context_agent import run_full_graph_agent
from query.agentic_agent import run_agentic_agent
from ingestion.entity_resolver import resolve_entities

load_dotenv(override=True)
console = Console()


def get_graph_client() -> Neo4jClient:
    cfg = neo4j_config()
    return Neo4jClient(uri=cfg["uri"], user=cfg["user"], password=cfg["password"])


async def ingest(filepath: str):
    console.print(f"[bold blue]Ingesting:[/] {filepath}")

    if filepath.endswith(".pdf"):
        chunks = chunk_pdf(filepath)
    else:
        with open(filepath) as f:
            chunks = chunk_text(f.read())

    console.print(f"[dim]Split into {len(chunks)} chunks[/]")

    triples = await ingest_chunks_parallel(chunks)
    console.print(f"[dim]Extracted {len(triples)} triples[/]")

    graph = get_graph_client()
    written = write_triples(graph, triples)
    total_nodes = graph.node_count()
    graph.close()

    console.print(
        f"[bold green]Done.[/] Wrote {written} unique triples. "
        f"Graph now has {total_nodes} entity nodes."
    )


def query(question: str, full_graph: bool = False, agentic: bool = False):
    import time
    if agentic:
        mode_label = "[dim]agentic[/]"
    elif full_graph:
        mode_label = "[dim]full-graph[/]"
    else:
        mode_label = "[dim]traversal[/]"

    console.print(f"\n[bold blue]Query ({mode_label}):[/] {question}\n")
    _start = time.perf_counter()

    if agentic:
        graph = get_graph_client()
        try:
            result = run_agentic_agent(question, graph)
        finally:
            graph.close()
    elif full_graph:
        graph = get_graph_client()
        try:
            result = run_full_graph_agent(question, graph)
        finally:
            graph.close()
    else:
        result = run_agent(question)

    elapsed = time.perf_counter() - _start
    console.print(f"[dim]Completed in {elapsed:.1f}s[/]\n")

    # --- Traversal path table ---
    if result.reasoning_path:
        table = Table(title="Traversal Path", show_lines=True, border_style="dim")
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Node", style="bold cyan", min_width=20)
        table.add_column("Relation", style="yellow", min_width=16)
        table.add_column("Score", justify="center", width=7)
        table.add_column("Reasoning", min_width=40)

        last_reasoning = None
        for i, step in enumerate(result.reasoning_path, 1):
            score = step.relevance_score
            if score >= 0.7:
                score_text = Text(f"{score:.2f}", style="green bold")
                status = "✓"
            else:
                score_text = Text(f"{score:.2f}", style="red")
                status = "✗"
            # Deduplicate thinking across batch mates — show once, then ↑
            if step.reasoning == last_reasoning:
                reasoning_cell = "[dim]↑ same thinking[/]"
            else:
                reasoning_cell = step.reasoning[:300] + ("…" if len(step.reasoning) > 300 else "")
                last_reasoning = step.reasoning
            table.add_row(
                f"{status}{i}",
                step.node_name,
                step.relation_type,
                score_text,
                reasoning_cell,
            )
        console.print(table)
    else:
        console.print("[dim]No traversal steps recorded.[/]\n")

    # --- Stats summary ---
    stats = (
        f"Nodes explored: [cyan]{result.nodes_explored}[/]  |  "
        f"Nodes retrieved: [cyan]{result.nodes_retrieved}[/]  |  "
        f"Max depth: [cyan]{result.hops_taken}[/]"
    )
    console.print(Panel(stats, title="Traversal Stats", border_style="dim", expand=False))

    # --- Final answer ---
    if agentic:
        console.print("[dim]Answer printed above.[/]")
    else:
        console.print(Panel(result.answer, title="Answer", border_style="green"))


def resolve(dry_run: bool = False):
    graph = get_graph_client()
    try:
        merged = resolve_entities(graph, dry_run=dry_run)
        if dry_run:
            console.print(f"[dim]Dry run — {merged} node(s) would be merged.[/]")
        else:
            console.print(f"[bold green]Done.[/] Merged {merged} duplicate node(s).")
    finally:
        graph.close()


def main():
    if len(sys.argv) < 2:
        console.print("[bold]Usage:[/]")
        console.print("  python main.py ingest [italic]<filepath>[/]")
        console.print("  python main.py query [italic]'<question>'[/]")
        console.print("  python main.py query --full-graph [italic]'<question>'[/]")
        console.print("  python main.py query --agentic [italic]'<question>'[/]")
        console.print("  python main.py resolve [italic][--dry-run][/]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "ingest":
        asyncio.run(ingest(sys.argv[2]))
    elif command == "query":
        args = sys.argv[2:]
        full_graph = "--full-graph" in args
        agentic = "--agentic" in args
        question = next((a for a in args if not a.startswith("--")), None)
        if not question:
            console.print("[red]No question provided.[/]")
            sys.exit(1)
        query(question, full_graph=full_graph, agentic=agentic)
    elif command == "resolve":
        dry_run = "--dry-run" in sys.argv[2:]
        resolve(dry_run=dry_run)
    else:
        console.print(f"[red]Unknown command:[/] {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
