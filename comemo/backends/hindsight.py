from __future__ import annotations

import logging
from typing import Any

from ..config import HindsightConfig
from .base import BackendAdapter

logger = logging.getLogger(__name__)


class HindsightBackend(BackendAdapter):

    def __init__(self, cfg: HindsightConfig) -> None:
        self._cfg = cfg
        self._client: Any = None

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
        from hindsight_client import Hindsight
        self._client = Hindsight(
            base_url=self._cfg.api_url,
            api_key=self._cfg.api_key,
        )

    def sync_turn(self, user: str, assistant: str, *, session_id: str = "") -> None:
        if self._client is None:
            return
        try:
            self._client.retain(
                bank_id=self._cfg.bank_id,
                content=f"User: {user}\nAssistant: {assistant}",
            )
        except Exception as exc:
            logger.warning("comemo/hindsight: sync_turn failed — %s", exc)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._client is None:
            return ""
        try:
            result = self._client.recall(
                bank_id=self._cfg.bank_id,
                query=query or "recent context",
            )
            entries = getattr(result, "results", None) or []
            return "\n".join(
                r.text for r in entries if getattr(r, "text", None)
            )
        except Exception as exc:
            logger.warning("comemo/hindsight: prefetch failed — %s", exc)
            return ""

    def on_session_end(self, messages: list[Any]) -> None:
        pass

    def shutdown(self) -> None:
        self._client = None
