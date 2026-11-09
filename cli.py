"""hermes comemo <subcommand> — discovered by Hermes at startup via discover_plugin_cli_commands()."""
from __future__ import annotations

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from comemo.cli import register_cli, _dispatch  # noqa: E402

__all__ = ["register_cli", "_dispatch"]
