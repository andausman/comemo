from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_CREATE = """
CREATE TABLE IF NOT EXISTS retry_queue (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    backend   TEXT NOT NULL,
    op        TEXT NOT NULL,
    payload   TEXT NOT NULL,
    attempts  INTEGER DEFAULT 0,
    created   REAL NOT NULL
)
"""
_MAX_ATTEMPTS = 5


class RetryQueue:

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.execute(_CREATE)
            self._conn.commit()
        return self._conn

    def push(self, backend: str, op: str, payload: dict[str, Any]) -> None:
        try:
            with self._lock:
                conn = self._ensure()
                conn.execute(
                    "INSERT INTO retry_queue (backend, op, payload, created) VALUES (?, ?, ?, ?)",
                    (backend, op, json.dumps(payload), time.time()),
                )
                conn.commit()
        except Exception as exc:
            logger.error("comemo/retry: push failed — %s", exc)

    def drain(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            with self._lock:
                conn = self._ensure()
                rows = conn.execute(
                    "SELECT id, backend, op, payload, attempts FROM retry_queue "
                    "WHERE attempts < ? ORDER BY id LIMIT ?",
                    (_MAX_ATTEMPTS, limit),
                ).fetchall()
            return [
                {
                    "id": r[0],
                    "backend": r[1],
                    "op": r[2],
                    "payload": json.loads(r[3]),
                    "attempts": r[4],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.debug("comemo/retry: drain failed — %s", exc)
            return []

    def ack(self, row_id: int) -> None:
        try:
            with self._lock:
                conn = self._ensure()
                conn.execute("DELETE FROM retry_queue WHERE id = ?", (row_id,))
                conn.commit()
        except Exception as exc:
            logger.debug("comemo/retry: ack failed — %s", exc)

    def increment(self, row_id: int) -> None:
        try:
            with self._lock:
                conn = self._ensure()
                conn.execute(
                    "UPDATE retry_queue SET attempts = attempts + 1 WHERE id = ?", (row_id,)
                )
                conn.commit()
        except Exception as exc:
            logger.debug("comemo/retry: increment failed — %s", exc)

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
