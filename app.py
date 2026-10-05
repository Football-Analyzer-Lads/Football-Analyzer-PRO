#!/usr/bin/env python3
"""Football Analyzer PRO application bootstrap.

The full V6.1.2 application source is stored in ordered chunks so the GitHub
source updater can transfer it reliably without truncating a large file.
At runtime the chunks are joined in memory and executed in this module's
namespace, preserving the original application behaviour.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parent
_parts = sorted(BASE.glob("app_source_*.py"))
if not _parts:
    raise RuntimeError("Application source chunks are missing.")

_source = "\n".join(p.read_text(encoding="utf-8").rstrip("\n") for p in _parts) + "\n"
exec(compile(_source, str(_parts[0]), "exec"), globals(), globals())
