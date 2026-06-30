"""CodeCompass setup wizard — writes opencode instructions file.

Usage:
    codecompass setup
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def run_setup() -> None:
    src = Path(__file__).resolve().parent.parent / "opencode" / "instructions.md"
    dest_dir = Path.home() / ".config" / "opencode" / "codecompass"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / "instructions.md"
    shutil.copy(src, dest)
    print(f"Wrote {dest}")

    config_block = {
        "instructions": [str(dest)],
    }

    opencode_config = Path.home() / ".config" / "opencode" / "opencode.json"
    print()
    if opencode_config.exists():
        print(f"Merge this into {opencode_config}:")
    else:
        print(f"Add this to {opencode_config}:")
    print()
    print(json.dumps(config_block, indent=2))
    print()
    print("Restart opencode after updating the config.")
