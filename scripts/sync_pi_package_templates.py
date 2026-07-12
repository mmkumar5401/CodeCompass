#!/usr/bin/env python3
"""Regenerate pi-package/templates/AGENTS.md from the canonical block in main.py."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as main_module  # noqa: E402

TEMPLATE = ROOT / "pi-package" / "templates" / "AGENTS.md"


def extract_agents_block() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        repo_path = os.path.join(tmp, "repo")
        os.makedirs(repo_path, exist_ok=True)
        main_module._register_project_agents_md(repo_path)  # noqa: SLF001
        return Path(repo_path, "AGENTS.md").read_text(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", "-o", default=str(TEMPLATE), help="Destination path")
    args = ap.parse_args()
    block = extract_agents_block()
    out = Path(args.output)
    out.write_text(block, encoding="utf-8")
    print(f"Updated {out}")


if __name__ == "__main__":
    main()
