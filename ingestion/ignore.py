"""Repo-level ignore rules — built-in skip dirs plus an optional `.ccignore`.

`.ccignore` sits at the repo root and holds gitignore-style globs, one per
line, `#` for comments:

    vendor/
    api/generated/*
    *.min.js

ponytail: fnmatch, not a gitignore engine — no `!` negation, no nested
`.ccignore` files. Add pathspec as a dep only if real repos need them.
"""

from __future__ import annotations

import fnmatch
import os

# Directory names skipped everywhere, no config needed.
DEFAULT_SKIP = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache",
    "coverage", "tmp", "cache", ".nx", "lcov-report",
}

IGNORE_FILE = ".ccignore"


def load_patterns(repo_path: str) -> list[str]:
    """Read `.ccignore` from the repo root. Missing file means no patterns."""
    path = os.path.join(repo_path, IGNORE_FILE)
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return []
    return [p for p in (line.split("#", 1)[0].strip().rstrip("/") for line in lines) if p]


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """True if a repo-relative path matches any pattern.

    A pattern with no `/` matches any path component (`vendor` kills every
    `vendor` dir); one with a `/` is anchored at the repo root. Either way,
    matching a directory also ignores everything under it.
    """
    rel = rel_path.replace(os.sep, "/").strip("/")
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/*"):
            return True
        if "/" not in pat and any(fnmatch.fnmatch(part, pat) for part in rel.split("/")):
            return True
    return False


def walk(repo_path: str, patterns: list[str] | None = None,
         skip_dirs: set[str] | None = None):
    """`os.walk` with DEFAULT_SKIP and `.ccignore` already applied.

    Yields (dirpath, dirnames, filenames) like os.walk, minus anything
    ignored. Pass `patterns` to reuse an already-loaded `.ccignore`.
    """
    if patterns is None:
        patterns = load_patterns(repo_path)
    skip = (skip_dirs or set()) | DEFAULT_SKIP

    for dirpath, dirnames, filenames in os.walk(repo_path):
        rel_dir = os.path.relpath(dirpath, repo_path)
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = [d for d in dirnames
                       if d not in skip and not is_ignored(prefix + d, patterns)]
        yield dirpath, dirnames, [f for f in filenames
                                  if not is_ignored(prefix + f, patterns)]
