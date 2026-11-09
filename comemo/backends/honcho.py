from __future__ import annotations

import logging
from typing import Any

from ..config import HonchoConfig
from .base import BackendAdapter

logger = logging.getLogger(__name__)


class HonchoBackend(BackendAdapter):

    def __init__(self, cfg: HonchoConfig) -> None:
        self._cfg = cfg
        self._client: Any = None
        self._user_peer: Any = None
        self._ai_peer: Any = None
        self._session_id = ""

    @property
    def name(self) -> str:
        return "honcho"

    def is_available(self) -> bool:
        if not self._cfg.enabled or not self._cfg.api_key:
            return False
        try:
            import honcho  # noqa: F401
            return True
        except ImportError:
            logger.debug("comemo/honcho: honcho-ai not installed")
            return False

    def initialize(self, session_id: str, hermes_home: str) -> None:
        from honcho import Honcho

        self._client = Honcho(
            workspace_id=self._cfg.workspace,
            api_key=self._cfg.api_key,
            base_url=self._cfg.base_url,
        )
        self._user_peer = self._client.peer(id="hermes-user")
        self._ai_peer = self._client.peer(id="hermes")
        self._session_id = session_id

    def sync_turn(self, user: str, assistant: str, *, session_id: str = "") -> None:
        if self._client is None:
            return
        sid = session_id or self._session_id
        session = self._client.session(sid)
        session.add_messages([
            self._user_peer.message(user),
            self._ai_peer.message(assistant),
        ])

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._user_peer is None:
            return ""
        try:
            context = self._user_peer.context()
            if not context:
                return ""
            if isinstance(context, str):
                return context.strip()
            # fallback: representation → peer_card → empty
            representation = getattr(context, "representation", None)
            if representation and str(representation).strip():
                return str(representation).strip()
            peer_card = getattr(context, "peer_card", None)
            if peer_card and str(peer_card).strip():
                return str(peer_card).strip()
            return ""
        except Exception as exc:
            logger.warning("comemo/honcho: prefetch failed — %s", exc)
            return ""

    def shutdown(self) -> None:
        self._user_peer = None
        self._ai_peer = None
        self._client = None
