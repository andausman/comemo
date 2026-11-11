from __future__ import annotations

import logging
import os
from typing import Any

from .backends.base import BackendAdapter
from .backends.honcho import HonchoBackend
from .backends.mem0 import Mem0Backend
from .backends.supermemory import SupermemoryBackend
from .config import ComemoConfig
from .fanout import FanOut
from .retry import RetryQueue

logger = logging.getLogger(__name__)


class ComemoCore:

    def __init__(self, cfg: ComemoConfig | None = None) -> None:
        self._cfg = cfg or ComemoConfig()
        self._backends: list[BackendAdapter] = []
        self._fanout: FanOut | None = None
        self._retry: RetryQueue | None = None

    @property
    def name(self) -> str:
        return "comemo"

    @property
    def active_backend_names(self) -> list[str]:
        return [b.name for b in self._backends]

    def is_available(self) -> bool:
        # Use active backends if already initialized; otherwise probe once without storing
        if self._backends:
            return True
        if not hasattr(self, "_probe_cache"):
            self._probe_cache = self._build_backends()
        return any(b.is_available() for b in self._probe_cache)

    def initialize(self, session_id: str, data_dir: str) -> None:
        data_dir = os.path.expanduser(data_dir)
        plugin_dir = os.path.join(data_dir, "comemo")
        os.makedirs(plugin_dir, exist_ok=True)
        retry_path = os.path.join(plugin_dir, "comemo-retry.db")
        self._retry = RetryQueue(retry_path)
        try:
            os.chmod(retry_path, 0o600)
        except OSError:
            pass

        self._backends = [b for b in self._build_backends() if b.is_available()]
        failed: list[BackendAdapter] = []
        for b in self._backends:
            try:
                b.initialize(session_id, data_dir)
            except Exception as exc:
                logger.warning("comemo: %s.initialize failed — %s", b.name, exc)
                failed.append(b)
        for b in failed:
            self._backends.remove(b)

        self._fanout = FanOut(self._backends, timeout=self._cfg.fan_out_timeout)
        logger.info("comemo: initialized — active providers: %s", self.active_backend_names)
        self._flush_retry_queue()

    def shutdown(self) -> None:
        for b in self._backends:
            try:
                b.shutdown()
            except Exception as e:
                logger.debug("comemo: %s.shutdown error — %s", b.name, e)
        if self._fanout:
            self._fanout.shutdown()
        if self._retry:
            self._retry.close()

    def write(self, user: str, assistant: str, *, session_id: str = "") -> None:
        if not self._backends or self._fanout is None:
            return
        failures = self._fanout.write(
            self._backends, "sync_turn", user, assistant, session_id=session_id
        )
        for backend_name, exc in failures.items():
            if exc is not None and self._retry is not None:
                self._retry.push(
                    backend_name,
                    "sync_turn",
                    {"user": user, "assistant": assistant, "session_id": session_id},
                )

    def read(self, query: str, *, session_id: str = "") -> str:
        if not self._backends or self._fanout is None:
            return ""
        chunks = self._fanout.read(self._backends, query, session_id=session_id)
        return self._merge(chunks)

    def on_session_end(self, messages: list[Any]) -> None:
        for b in self._backends:
            try:
                b.on_session_end(messages)
            except Exception as exc:
                logger.warning("comemo: %s.on_session_end failed — %s", b.name, exc)

    def on_pre_compress(self, messages: list[Any]) -> None:
        for b in self._backends:
            try:
                b.on_pre_compress(messages)
            except Exception as exc:
                logger.warning("comemo: %s.on_pre_compress failed — %s", b.name, exc)

    def system_prompt_block(self) -> str:
        if not self._backends:
            return ""
        names = ", ".join(b.name for b in self._backends)
        return f"[Memory: comemo — active providers: {names}]"

    def _build_backends(self) -> list[BackendAdapter]:
        return [
            HonchoBackend(self._cfg.honcho),
            Mem0Backend(self._cfg.mem0),
            SupermemoryBackend(self._cfg.supermemory),
        ]

    def _merge(self, chunks: list[str]) -> str:
        seen: set[str] = set()
        lines: list[str] = []
        for chunk in chunks:
            for line in chunk.splitlines():
                stripped = line.strip()
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    lines.append(stripped)
        return "\n".join(lines)

    def _flush_retry_queue(self) -> None:
        if not self._retry or not self._backends:
            return
        backend_map = {b.name: b for b in self._backends}
        pending = self._retry.drain()
        replayed = 0
        for item in pending:
            b = backend_map.get(item["backend"])
            if b is None:
                continue
            try:
                payload = item["payload"]
                if item["op"] == "sync_turn":
                    b.sync_turn(
                        payload["user"],
                        payload["assistant"],
                        session_id=payload.get("session_id", ""),
                    )
                self._retry.ack(item["id"])
                replayed += 1
            except Exception:
                self._retry.increment(item["id"])
        if replayed:
            logger.info("comemo: replayed %d queued write(s) from retry queue", replayed)
