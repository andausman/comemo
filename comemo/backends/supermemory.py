from __future__ import annotations

import logging
import time
from typing import Any

from ..config import SupermemoryConfig
from .base import BackendAdapter

logger = logging.getLogger(__name__)


class SupermemoryBackend(BackendAdapter):

    def __init__(self, cfg: SupermemoryConfig) -> None:
        self._cfg = cfg
        self._client: Any = None
        self._session_id = ""

    @property
    def name(self) -> str:
        return "supermemory"

    def is_available(self) -> bool:
        if not self._cfg.enabled or not self._cfg.api_key:
            return False
        try:
            import supermemory  # noqa: F401
            return True
        except ImportError:
            logger.debug("comemo/supermemory: supermemory not installed — pip install supermemory")
            return False

    def initialize(self, session_id: str, hermes_home: str) -> None:
        from supermemory import Supermemory
        self._client = Supermemory(
            api_key=self._cfg.api_key,
            base_url=self._cfg.base_url,
        )
        self._session_id = session_id

    def _turn_id(self) -> str:
        # unique per turn — supermemory overwrites duplicate IDs
        return f"{self._session_id}_{int(time.time() * 1000)}"

    def sync_turn(self, user: str, assistant: str, *, session_id: str = "") -> None:
        if self._client is None:
            return
        try:
            self._client.add(
                namespace=self._cfg.namespace,
                content=f"User: {user}\nAssistant: {assistant}",
                id=self._turn_id(),
                task_type="memory",
            )
        except Exception as exc:
            logger.warning("comemo/supermemory: sync_turn failed — %s", exc)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._client is None:
            return ""
        try:
            if query.strip():
                results = self._client.search(
                    namespace=self._cfg.namespace,
                    query=query,
                    limit=5,
                )
                lines = [r.content for r in results.results if getattr(r, "content", None)]
            else:
                # no query yet — fetch 5 most recent memories by date
                page = self._client.list(
                    self._cfg.namespace,
                    "memories",
                    sort="createdAt",
                    order="desc",
                    limit=5,
                )
                items = getattr(page, "memories", None) or getattr(page, "results", None) or []
                lines = [r.content for r in items if getattr(r, "content", None)]
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("comemo/supermemory: prefetch failed — %s", exc)
            return ""

    def shutdown(self) -> None:
        self._client = None
