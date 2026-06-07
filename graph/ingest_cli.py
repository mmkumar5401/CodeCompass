#!/usr/bin/env python3
"""
Ingest a new source into the knowledge graph — for use by Claude Code.

Fetches (if URL), chunks, extracts entities/relationships, and writes everything
to Neo4j permanently, tagged as session_id="claude-code".

Usage:
  python graph/ingest_cli.py --url "https://arxiv.org/abs/2105.00188"
  python graph/ingest_cli.py --file path/to/document.pdf
  python graph/ingest_cli.py --file path/to/document.txt
  python graph/ingest_cli.py --text "raw text to ingest directly"
"""
import sys
import argparse
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, __file__.rsplit("/graph", 1)[0])

from config import neo4j_config
from graph.neo4j_client import Neo4jClient
from ingestion.chunker import chunk_text
from ingestion.reader_agent import extract_triples_parallel_sync


def _read_file(path: str) -> str:
    if path.lower().endswith(".pdf"):
        try:
            import io
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            print(f"[ingest] PDF read failed: {e}")
            sys.exit(1)
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def _fetch_url(url: str) -> str:
    """Fetch URL — arxiv abstract pages are redirected to PDF."""
    import re
    import io
    import urllib.request

    HEADERS = {"User-Agent": "Mozilla/5.0"}

    arxiv_match = re.match(r"https?://arxiv\.org/abs/(.+?)(?:\s|$)", url)
    if arxiv_match:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_match.group(1)}"
        print(f"[ingest] arxiv detected — fetching PDF: {pdf_url}")
        try:
            import PyPDF2
            req = urllib.request.Request(pdf_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                pdf_bytes = resp.read()
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if text:
                return text
        except Exception as e:
            print(f"[ingest] PDF fetch failed ({e}), falling back to HTML")

    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    import re as _re
    text = _re.sub(r"<[^>]+>", " ", raw)
    text = _re.sub(r"\s+", " ", text).strip()
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a source into the knowledge graph."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url",  help="URL to fetch and ingest (arxiv PDFs detected automatically)")
    group.add_argument("--file", help="Path to a PDF or text file")
    group.add_argument("--text", help="Raw text to ingest directly")
    args = parser.parse_args()

    # --- Acquire text ---
    if args.url:
        print(f"[ingest] fetching {args.url[:80]}...")
        try:
            text = _fetch_url(args.url)
        except Exception as e:
            print(f"[ingest] fetch failed: {e}")
            sys.exit(1)
    elif args.file:
        print(f"[ingest] reading {args.file}...")
        text = _read_file(args.file)
    else:
        text = args.text

    if not text or not text.strip():
        print("[ingest] no content to ingest.")
        sys.exit(1)

    # --- Chunk + extract (parallel) ---
    chunks = chunk_text(text)
    print(f"[ingest] {len(chunks)} chunks — extracting triples in parallel...")
    triples = extract_triples_parallel_sync(chunks)

    if not triples:
        print("[ingest] no triples extracted — nothing written.")
        sys.exit(0)

    # --- Write to graph ---
    cfg   = neo4j_config()
    graph = Neo4jClient(uri=cfg["uri"], user=cfg["user"], password=cfg["password"])

    try:
        new_names: set[str] = set()
        for triple in triples:
            graph.write_triple(triple, session_id="claude-code")
            new_names.add(triple.entity_from.name)
            new_names.add(triple.entity_to.name)

        print(f"[ingest] done — {len(triples)} triples, {len(new_names)} entities written to graph")
        sample = sorted(new_names)[:25]
        print(f"[ingest] nodes available for querying: {sample}")
        print("\nUse query_cli.py to explore these nodes:")
        seeds = ",".join(sample[:5])
        print(f'  python graph/query_cli.py --seeds "{seeds}"')
    finally:
        graph.close()


if __name__ == "__main__":
    main()
