from __future__ import annotations

import logging
from typing import Any

from ..config import Mem0Config
from .base import BackendAdapter

logger = logging.getLogger(__name__)


class Mem0Backend(BackendAdapter):

    def __init__(self, cfg: Mem0Config) -> None:
        self._cfg = cfg
        self._client: Any = None

    @property
    def name(self) -> str:
        return "mem0"

    def is_available(self) -> bool:
        if not self._cfg.enabled or not self._cfg.api_key:
            return False
        try:
            import mem0  # noqa: F401
            return True
        except ImportError:
            logger.debug("comemo/mem0: mem0ai not installed — pip install mem0ai")
            return False

    def initialize(self, session_id: str, hermes_home: str) -> None:
        from mem0 import MemoryClient
        kwargs: dict[str, Any] = {"api_key": self._cfg.api_key}
        if self._cfg.base_url:
            kwargs["host"] = self._cfg.base_url
        self._client = MemoryClient(**kwargs)

    def sync_turn(self, user: str, assistant: str, *, session_id: str = "") -> None:
        if self._client is None:
            return
        self._client.add(
            messages=[
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ],
            user_id=self._cfg.user_id,
            agent_id=self._cfg.agent_id,
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._client is None:
            return ""
        try:
            if query.strip():
                raw = self._client.search(query=query, filters={"user_id": self._cfg.user_id}, top_k=10)
            else:
                # Broad recall (inspect / empty query) — get_all avoids the empty-query rejection
                raw = self._client.get_all(filters={"user_id": self._cfg.user_id})
            if not raw:
                return ""
            items = raw.get("results") if isinstance(raw, dict) else raw
            if not items:
                return ""
            lines = []
            for r in items:
                if isinstance(r, str):
                    lines.append(r)
                elif isinstance(r, dict):
                    lines.append(r.get("memory") or r.get("text") or "")
            return "\n".join(l for l in lines if l)
        except Exception as exc:
            logger.warning("comemo/mem0: prefetch failed — %s", exc)
            return ""

    def shutdown(self) -> None:
        self._client = None
