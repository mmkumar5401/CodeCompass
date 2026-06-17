"""CodeCompass CLI — entry point for pip-installed codecompass commands.

Usage:
    codecompass ingest-code /path/to/repo --project <name>
    codecompass watch /path/to/repo --project <name>
    codecompass dedupe-edges [--dry-run]
"""

from main import main as _main


def main() -> None:
    _main()
