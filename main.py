"""CodeCompass — code dependency index for LLM coding agents.

Commands:
    ingest-code <repo_path> --project <name> [--normalize] [--dump-triples <out.json>]
    load-triples <triples.json> --project <name>
    watch <repo_path> --project <name>
    dedupe-edges [--dry-run]
"""

import sys
from dotenv import load_dotenv
from rich.console import Console

from graph.code_graph_client import get_client
from ingestion.code_parser import parse_directory
from ingestion.hierarchy_builder import build_hierarchy, get_file_id_map
from ingestion.file_watcher import FileWatcher

load_dotenv(override=True)
console = Console()


def ingest_code(repo_path: str, project_name: str, normalize: bool = False, dump_triples: str | None = None) -> None:
    """Ingest a codebase into the code knowledge graph.

    Phase 1: Walk the repo and write the Project → Folder → File skeleton.
    Phase 2: Parse every source file with tree-sitter into CodeTriples.
    Phase 3: Normalize entity names via Haiku (only if --normalize is passed).
    Phase 4: Write all triples to the project graph.

    If dump_triples is given, raw triples are written to that JSON file and
    the ingest stops — use this to normalize externally, then reload with
    load-triples.
    """
    import os
    import json
    from tqdm import tqdm

    repo_path = os.path.abspath(repo_path)
    console.print(f"[bold blue]Ingesting codebase:[/] {repo_path}")
    console.print(f"[dim]Project name:[/] {project_name}")

    client = get_client(project_name)
    client.ensure_indexes()

    console.print("[dim]Phase 1/4 — Building hierarchy…[/]")
    file_id_map = build_hierarchy(repo_path, project_name, client)
    console.print(f"[dim]  {len(file_id_map)} source files indexed[/]")

    console.print("[dim]Phase 2/4 — Parsing source files…[/]")
    raw_triples = parse_directory(repo_path, progress=True)
    console.print(f"[dim]  {len(raw_triples)} raw triples extracted[/]")

    if not raw_triples:
        console.print("[yellow]No triples extracted — check that the repo contains supported files.[/]")
        client.close()
        return

    if dump_triples:
        data = [
            {
                "from_entity": t.from_entity,
                "from_type": t.from_type,
                "relation_type": t.relation_type,
                "to_entity": t.to_entity,
                "to_type": t.to_type,
                "source_file": t.source_file,
                "line_number": t.line_number,
            }
            for t in raw_triples
        ]
        with open(dump_triples, "w") as f:
            json.dump(data, f, indent=2)
        client.close()
        console.print(f"[bold green]Dumped {len(raw_triples)} raw triples to:[/] {dump_triples}")
        console.print("[dim]Normalize them, then run: python main.py load-triples <file> --project <name>[/]")
        return

    if normalize:
        from ingestion.code_normalizer import normalize_triples
        console.print("[dim]Phase 3/4 — Normalizing triples via Haiku…[/]")
        triples = normalize_triples(raw_triples, progress=True)
        console.print(f"[dim]  {len(triples)} triples after normalization[/]")
    else:
        console.print("[dim]Phase 3/4 — Skipping normalization (pass --normalize to enable)[/]")
        triples = raw_triples

    console.print("[dim]Phase 4/4 — Writing to Neo4j…[/]")
    written = client.write_code_triples_batch(triples, file_id_map, project_name)

    total_nodes = client.node_count()
    client.close()

    console.print(
        f"[bold green]Done.[/] Wrote {written} triples. "
        f"Graph now has {total_nodes} nodes."
    )
    _register_project_agents_md(repo_path, project_name)


_CODECOMPASS_START = "<!-- codecompass-code-graph-start -->"
_CODECOMPASS_END = "<!-- codecompass-code-graph-end -->"


def _register_project_agents_md(repo_path: str, project_name: str) -> None:
    """Write or update the Code graph section in the project's AGENTS.md.

    Uses HTML comment markers so re-ingesting safely replaces only that block.
    """
    import os, re

    block = (
        f"{_CODECOMPASS_START}\n"
        f"## Code graph\n\n"
        f"This project is indexed in the CodeCompass code graph as `{project_name}`. "
        f"Query it before editing to know what to read:\n\n"
        f"```bash\n"
        f"# Run from your codecompass install directory:\n"
        f"python -m graph.code_query_cli --deps <file> --project {project_name}\n"
        f"python -m graph.code_query_cli --impact \"<function>\" --project {project_name}\n"
        f"python -m graph.code_query_cli --tree {project_name}\n"
        f"```\n\n"
        f"Re-ingest after adding files:\n"
        f"```bash\n"
        f"python main.py ingest-code {repo_path} --project {project_name}\n"
        f"```\n"
        f"{_CODECOMPASS_END}"
    )

    agents_md_path = os.path.join(repo_path, "AGENTS.md")

    if os.path.exists(agents_md_path):
        with open(agents_md_path) as f:
            content = f.read()
        if _CODECOMPASS_START in content:
            pattern = re.escape(_CODECOMPASS_START) + r".*?" + re.escape(_CODECOMPASS_END)
            new_content = re.sub(pattern, block, content, flags=re.DOTALL)
        else:
            new_content = content.rstrip() + f"\n\n---\n\n{block}\n"
    else:
        new_content = block + "\n"

    with open(agents_md_path, "w") as f:
        f.write(new_content)

    console.print(f"[dim]  Registered in {agents_md_path}[/]")


def load_triples(triples_file: str, project_name: str) -> None:
    """Load pre-normalized triples from a JSON file into the code graph."""
    import json
    from models.code_types import CodeTriple

    with open(triples_file) as f:
        data = json.load(f)

    triples = [
        CodeTriple(
            from_entity=d["from_entity"],
            from_type=d["from_type"],
            relation_type=d["relation_type"],
            to_entity=d["to_entity"],
            to_type=d["to_type"],
            source_file=d["source_file"],
            line_number=d["line_number"],
        )
        for d in data
    ]

    console.print(f"[bold blue]Loading {len(triples)} triples from:[/] {triples_file}")
    client = get_client(project_name)
    file_id_map = get_file_id_map(project_name, client)

    written = client.write_code_triples_batch(triples, file_id_map, project_name)

    total_nodes = client.node_count()
    client.close()
    console.print(f"[bold green]Done.[/] Wrote {written} triples. Graph now has {total_nodes} nodes.")


def watch_code(repo_path: str, project_name: str) -> None:
    """Watch a repo for file changes and keep the code graph updated incrementally."""
    import os
    repo_path = os.path.abspath(repo_path)
    client = get_client(project_name)
    file_id_map = build_hierarchy(repo_path, project_name, client)
    watcher = FileWatcher(repo_path, project_name, client, file_id_map)
    watcher.start()


def dedupe_edges(dry_run: bool = False) -> None:
    """Remove duplicate RELATION edges (same from-node, type, to-node)."""
    from config import neo4j_config
    from neo4j import GraphDatabase

    cfg = neo4j_config()
    driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))

    with driver.session() as session:
        result = session.run("""
            MATCH (a)-[r:RELATION]->(b)
            WITH a, r.type AS rel_type, b, collect(r) AS rels
            WHERE size(rels) > 1
            RETURN count(*) AS dup_groups, sum(size(rels) - 1) AS removable
        """)
        row = result.single()
        dup_groups = row["dup_groups"]
        removable = row["removable"]

        if removable == 0:
            console.print("[dim]No duplicate edges found.[/]")
            driver.close()
            return

        console.print(f"[dim]Found {dup_groups} duplicate groups, {removable} removable edges.[/]")

        if dry_run:
            console.print("[dim]Dry run — nothing deleted.[/]")
        else:
            session.run("""
                MATCH (a)-[r:RELATION]->(b)
                WITH a, r.type AS rel_type, b, collect(r) AS rels
                WHERE size(rels) > 1
                FOREACH (r IN tail(rels) | DELETE r)
            """)
            console.print(f"[bold green]Done.[/] Removed {removable} duplicate edge(s).")

    driver.close()


def main():
    if len(sys.argv) < 2:
        console.print("[bold]Usage:[/]")
        console.print("  python main.py ingest-code [italic]<repo_path>[/] --project [italic]<name>[/]")
        console.print("  python main.py ingest-code [italic]<repo_path>[/] --project [italic]<name>[/] --normalize")
        console.print("  python main.py ingest-code [italic]<repo_path>[/] --project [italic]<name>[/] --dump-triples [italic]<out.json>[/]")
        console.print("  python main.py load-triples [italic]<triples.json>[/] --project [italic]<name>[/]")
        console.print("  python main.py watch [italic]<repo_path>[/] --project [italic]<name>[/]")
        console.print("  python main.py dedupe-edges [italic][--dry-run][/]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "ingest-code":
        args = sys.argv[2:]
        if not args:
            console.print("[red]Usage: python main.py ingest-code <repo_path> --project <name>[/]")
            sys.exit(1)
        repo_path = args[0]
        project_name = "default"
        normalize = "--normalize" in args
        dump_triples = None
        if "--dump-triples" in args:
            idx = args.index("--dump-triples")
            if idx + 1 < len(args):
                dump_triples = args[idx + 1]
        if "--project" in args:
            idx = args.index("--project")
            if idx + 1 < len(args):
                project_name = args[idx + 1]
        ingest_code(repo_path, project_name, normalize=normalize, dump_triples=dump_triples)

    elif command == "load-triples":
        args = sys.argv[2:]
        if not args:
            console.print("[red]Usage: python main.py load-triples <triples.json> --project <name>[/]")
            sys.exit(1)
        triples_file = args[0]
        project_name = "default"
        if "--project" in args:
            idx = args.index("--project")
            if idx + 1 < len(args):
                project_name = args[idx + 1]
        load_triples(triples_file, project_name)

    elif command == "watch":
        args = sys.argv[2:]
        if not args:
            console.print("[red]Usage: python main.py watch <repo_path> --project <name>[/]")
            sys.exit(1)
        repo_path = args[0]
        project_name = "default"
        if "--project" in args:
            idx = args.index("--project")
            if idx + 1 < len(args):
                project_name = args[idx + 1]
        watch_code(repo_path, project_name)

    elif command == "dedupe-edges":
        dry_run = "--dry-run" in sys.argv[2:]
        dedupe_edges(dry_run=dry_run)

    else:
        console.print(f"[red]Unknown command:[/] {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
