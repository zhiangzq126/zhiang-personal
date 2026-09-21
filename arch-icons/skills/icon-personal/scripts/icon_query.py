#!/usr/bin/env python3
"""Compatibility entry; delegate to the canonical Arch Icons skill."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[2]/'arch-icons/scripts/icon_query.py'), run_name='__main__')
