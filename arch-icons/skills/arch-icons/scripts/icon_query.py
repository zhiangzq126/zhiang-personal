#!/usr/bin/env python3
"""Portable read-only entry point for the shared icon library."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(os.environ.get("ARCH_ICONS_ROOT") or os.environ.get("ICON_PERSONAL_ROOT") or str(Path(__file__).resolve().parents[3])).expanduser().resolve()
    cli = root / "scripts/iconlib.py"
    if len(sys.argv) < 2 or sys.argv[1] not in ("search", "resolve", "show"):
        print(json.dumps({"error": "Use search, resolve or show; this entry point is read-only"}))
        return 1
    if not cli.is_file() or not (root / "docs/agent-contract.md").is_file():
        print(json.dumps({"error": "Set ARCH_ICONS_ROOT to the arch-icons project directory"}))
        return 1
    return subprocess.run([sys.executable, str(cli), *sys.argv[1:]],
                          env={**os.environ, "ARCH_ICONS_ROOT": str(root)}).returncode


if __name__ == "__main__":
    sys.exit(main())
