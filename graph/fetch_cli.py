#!/usr/bin/env python3
"""
Fetch a URL and print clean text to stdout — for use by Claude Code.

Claude Code reads the output and extracts entities/relationships natively,
then writes them via remember_batch_cli.py — no Anthropic API credits needed.

Usage:
  python graph/fetch_cli.py "https://arxiv.org/abs/2105.00188"
  python graph/fetch_cli.py "https://example.com/paper.pdf"
"""
import sys
import re
import io
import urllib.request

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch(url: str) -> str:
    # arxiv: prefer PDF over noisy HTML abstract page
    arxiv_match = re.match(r"https?://arxiv\.org/abs/(.+?)(?:\s|$)", url)
    if arxiv_match:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_match.group(1)}"
        print(f"[fetch] arxiv detected — fetching PDF: {pdf_url}", file=sys.stderr)
        try:
            import PyPDF2
            req = urllib.request.Request(pdf_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                pdf_bytes = resp.read()
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if text:
                return text
            print("[fetch] PDF text empty, falling back to HTML", file=sys.stderr)
        except Exception as e:
            print(f"[fetch] PDF fetch failed ({e}), falling back to HTML", file=sys.stderr)

    # Generic URL — strip HTML tags
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def main():
    if len(sys.argv) < 2:
        print("Usage: python graph/fetch_cli.py <url>")
        sys.exit(1)

    url = sys.argv[1].strip()
    try:
        text = fetch(url)
    except Exception as e:
        print(f"[fetch] failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not text:
        print("[fetch] no content returned", file=sys.stderr)
        sys.exit(1)

    print(text)


if __name__ == "__main__":
    main()
