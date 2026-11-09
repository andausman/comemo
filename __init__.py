from __future__ import annotations

import sys
from pathlib import Path

# Hermes loads this file directly via importlib.util.spec_from_file_location as
# _hermes_user_memory.comemo. The repo root (this file's parent) may not be on
# sys.path in that context, so add it so the comemo subpackage is importable.
_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from agent.memory_provider import MemoryProvider as _BaseMemoryProvider  # noqa: F401
except ImportError:
    class _BaseMemoryProvider:  # type: ignore[no-redef]
        pass

from comemo import register  # noqa: F401, E402
from comemo.adapters.hermes import HermesAdapter  # noqa: E402


class MemoryProvider(HermesAdapter):  # type: ignore[misc]
    """MemoryProvider subclass — Hermes plugin loader finds this via static scan."""
    pass
