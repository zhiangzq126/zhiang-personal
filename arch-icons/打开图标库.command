#!/bin/zsh
icon_project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$icon_project_dir" || exit 1
exec python3 scripts/iconlib.py serve --port 0 --open
