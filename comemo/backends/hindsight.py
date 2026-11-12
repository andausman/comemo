from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..config import HindsightConfig
from .base import BackendAdapter

logger = logging.getLogger(__name__)


class HindsightBackend(BackendAdapter):

    def __init__(self, cfg: HindsightConfig) -> None:
        self._cfg = cfg
        self._client: Any = None
        self._session_id = ""

    @property
    def name(self) -> str:
        return "hindsight"

    def is_available(self) -> bool:
        if not self._cfg.enabled or not self._cfg.api_key:
            return False
        try:
            import hindsight_client  # noqa: F401
            return True
        except ImportError:
            logger.debug("comemo/hindsight: hindsight-client not installed — reinstall the plugin: hermes plugins install comemo")
            return False

    def initialize(self, session_id: str, hermes_home: str) -> None:
        from hindsight_client import AsyncHindsightClient
        self._client = AsyncHindsightClient(
            api_key=self._cfg.api_key,
            base_url=self._cfg.api_url,
        )
        self._session_id = session_id

    def sync_turn(self, user: str, assistant: str, *, session_id: str = "") -> None:
        if self._client is None:
            return
        try:
            asyncio.run(self._client.retain(
                content=f"User: {user}\nAssistant: {assistant}",
                bank_id=self._cfg.bank_id,
                session_id=session_id or self._session_id,
                source="conversation",
            ))
        except Exception as exc:
            logger.warning("comemo/hindsight: sync_turn failed — %s", exc)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._client is None:
            return ""
        try:
            result = asyncio.run(self._client.recall(
                query=query or "recent context",
                bank_id=self._cfg.bank_id,
                session_id=session_id or self._session_id,
                strategy="hybrid",
                limit=10,
            ))
            memories = getattr(result, "memories", None) or []
            return "\n".join(
                m.content for m in memories if getattr(m, "content", None)
            )
        except Exception as exc:
            logger.warning("comemo/hindsight: prefetch failed — %s", exc)
            return ""

    def on_session_end(self, messages: list[Any]) -> None:
        if self._client is None:
            return
        try:
            asyncio.run(self._client.flush(bank_id=self._cfg.bank_id))
        except Exception:
            pass

    def shutdown(self) -> None:
        if self._client is not None:
            try:
                asyncio.run(self._client.close())
            except Exception:
                pass
        self._client = None
