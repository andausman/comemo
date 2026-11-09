from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BackendAdapter(ABC):
    """Interface for a single memory provider."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool:
        # Must not make network calls
        ...

    @abstractmethod
    def initialize(self, session_id: str, hermes_home: str) -> None: ...

    @abstractmethod
    def sync_turn(self, user: str, assistant: str, *, session_id: str = "") -> None: ...

    @abstractmethod
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        # Return empty string on failure rather than raising
        ...

    def on_session_end(self, messages: list[Any]) -> None:
        pass

    def on_pre_compress(self, messages: list[Any]) -> None:
        pass

    def shutdown(self) -> None:
        pass
