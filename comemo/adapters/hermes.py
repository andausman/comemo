from __future__ import annotations

import logging
import os
import threading
from typing import Any

import yaml

from ..config import ComemoConfig
from ..core import ComemoCore

logger = logging.getLogger(__name__)


def _get_hermes_home() -> str:
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home()
    except Exception:
        return os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def _load_cfg_from_file() -> "ComemoConfig":
    # read comemo section from ~/.hermes/config.yaml when no cfg is injected
    hermes_home = _get_hermes_home()
    config_path = os.path.join(hermes_home, "config.yaml")
    try:
        with open(config_path) as f:
            raw = (yaml.safe_load(f) or {}).get("plugins", {}).get("comemo", {})
    except Exception:
        raw = {}
    return ComemoConfig.load(raw)


try:
    from agent.memory_provider import MemoryProvider as _HermesBase

    _BASE: type = _HermesBase
except ImportError:
    _BASE = object

try:
    from agent.memory_provider import spawn_context_thread as _spawn
except ImportError:
    def _spawn(target: Any, *, name: str = "comemo-bg") -> threading.Thread:  # type: ignore[misc]
        return threading.Thread(target=target, name=name, daemon=True)


def _fire(fn: Any, name: str = "comemo-fire") -> None:
    t = _spawn(fn, name=name)
    t.daemon = True
    t.start()


class HermesAdapter(_BASE):  # type: ignore[misc,valid-type]

    def __init__(self, cfg: ComemoConfig | None = None, data_dir: str | None = None) -> None:
        if cfg is None:
            cfg = _load_cfg_from_file()
        self._core = ComemoCore(cfg)
        self._data_dir = data_dir
        self._prefetch_cache: str | None = None
        self._prefetch_count: int = 0

    @property
    def name(self) -> str:
        return self._core.name

    def is_available(self) -> bool:
        return self._core.is_available()

    def initialize(self, session_id: str, hermes_home: str = "", **kwargs: Any) -> None:
        data_dir = os.path.expanduser(
            hermes_home
            or self._data_dir
            or os.environ.get("HERMES_HOME")
            or "~/.hermes"
        )
        self._core.initialize(session_id, data_dir)

    def shutdown(self) -> None:
        self._core.shutdown()

    def system_prompt_block(self) -> str:
        return self._core.system_prompt_block()

    def sync_turn(
        self,
        user: str,
        assistant: str,
        *,
        session_id: str = "",
        messages: Any = None,
    ) -> None:
        # Fire-and-forget — Hermes must not be blocked waiting on memory writes
        _fire(lambda: self._core.write(user, assistant, session_id=session_id), name="comemo-write")

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        def _bg() -> None:
            result = self._core.read(query, session_id=session_id)
            self._prefetch_cache = result
            self._prefetch_count = sum(1 for l in result.splitlines() if l.strip())

        _fire(_bg, name="comemo-prefetch")

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        # serve from cache; fall back to live read on first turn
        if self._prefetch_cache is not None:
            return self._prefetch_cache
        result = self._core.read(query, session_id=session_id)
        self._prefetch_cache = result
        self._prefetch_count = sum(1 for l in result.splitlines() if l.strip())
        return result

    def recall_status(self) -> Any:
        try:
            from agent.memory_provider import RecallStatus
            names = self._core.active_backend_names
            label = f"comemo ({', '.join(names)})" if names else "comemo"
            return RecallStatus(label=label, count=self._prefetch_count, glyph="🧠")
        except ImportError:
            return None

    def on_session_end(self, messages: list[Any]) -> None:
        self._core.on_session_end(messages)
        self._prefetch_cache = None
        self._prefetch_count = 0

    def on_pre_compress(
        self, messages: list[Any], *, require_checkpoint: bool = False
    ) -> None:
        self._core.on_pre_compress(messages)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_memory",
                "description": (
                    "Search stored memories across all configured memory providers "
                    "(Honcho, Mem0, Supermemory)"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for in memory",
                        }
                    },
                    "required": ["query"],
                },
            }
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> Any:
        if tool_name == "search_memory":
            return self._core.read(args.get("query", ""))
        return None

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {"key": "honcho.enabled",
             "description": "Enable Honcho (cloud conversation memory — honcho.dev)",
             "type": "boolean", "default": False},
            {"key": "honcho.api_key",
             "description": "Honcho API key (honcho.dev)",
             "type": "secret", "env_var": "HONCHO_API_KEY"},
            {"key": "honcho.workspace",
             "description": "Honcho workspace name — isolates memories per team or profile",
             "type": "string", "default": "hermes"},
            {"key": "mem0.enabled",
             "description": "Enable Mem0 (semantic memory with auto-extraction — mem0.ai)",
             "type": "boolean", "default": False},
            {"key": "mem0.api_key",
             "description": "Mem0 API key (mem0.ai)",
             "type": "secret", "env_var": "MEM0_API_KEY"},
            {"key": "mem0.user_id",
             "description": "Mem0 user ID — scopes memories to this identity",
             "type": "string", "default": "hermes-user"},
            {"key": "supermemory.enabled",
             "description": "Enable Supermemory (3-layer retrieval — supermemory.ai)",
             "type": "boolean", "default": False},
            {"key": "supermemory.api_key",
             "description": "Supermemory API key (supermemory.ai)",
             "type": "secret", "env_var": "SUPERMEMORY_API_KEY"},
            {"key": "supermemory.namespace",
             "description": "Supermemory namespace — isolates memories per profile",
             "type": "string", "default": "hermes"},
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        # Unflatten dotted keys — skip secret api_key fields, Hermes stores those
        comemo_cfg: dict[str, Any] = {}
        for key, val in values.items():
            if key.endswith(".api_key"):
                continue
            if "." in key:
                provider, field = key.split(".", 1)
                comemo_cfg.setdefault(provider, {})[field] = val
            else:
                comemo_cfg[key] = val

        # Write only plugins.comemo — leave the rest of config.yaml untouched
        try:
            from hermes_cli import config as hermes_config
            hermes_config.set_plugin_config("comemo", comemo_cfg)
        except Exception:
            config_path = os.path.join(hermes_home, "config.yaml")
            cfg: dict[str, Any] = {}
            if os.path.exists(config_path):
                with open(config_path) as f:
                    cfg = yaml.safe_load(f) or {}
            cfg.setdefault("plugins", {})["comemo"] = comemo_cfg
            with open(config_path, "w") as f:
                yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True)
