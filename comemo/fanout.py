from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, wait

from .backends.base import BackendAdapter

logger = logging.getLogger(__name__)


class FanOut:

    def __init__(self, backends: list[BackendAdapter], timeout: float = 5.0) -> None:
        self._timeout = timeout
        self._pool = ThreadPoolExecutor(
            max_workers=max(len(backends), 1),
            thread_name_prefix="comemo-fanout",
        )

    def write(
        self,
        backends: list[BackendAdapter],
        fn_name: str,
        *args: object,
        **kwargs: object,
    ) -> dict[str, Exception | None]:
        futures = {
            self._pool.submit(getattr(b, fn_name), *args, **kwargs): b
            for b in backends
        }
        results: dict[str, Exception | None] = {}
        done, pending = wait(futures.keys(), timeout=self._timeout)

        for f in done:
            b = futures[f]
            exc = f.exception()
            results[b.name] = exc
            if exc:
                logger.warning("comemo: %s.%s failed — %s", b.name, fn_name, exc)

        for f in pending:
            b = futures[f]
            results[b.name] = TimeoutError(f"{b.name}.{fn_name} timed out after {self._timeout}s")
            logger.warning("comemo: %s.%s timed out", b.name, fn_name)
            f.cancel()

        return results

    def read(
        self,
        backends: list[BackendAdapter],
        query: str,
        **kwargs: object,
    ) -> list[str]:
        futures = {
            self._pool.submit(b.prefetch, query, **kwargs): b
            for b in backends
        }
        results: list[str] = []
        done, pending = wait(futures.keys(), timeout=self._timeout)

        for f in done:
            b = futures[f]
            try:
                text = f.result()
                if text and text.strip():
                    results.append(text.strip())
            except Exception as exc:
                logger.warning("comemo: %s.prefetch failed — %s", b.name, exc)

        for f in pending:
            b = futures[f]
            logger.warning("comemo: %s.prefetch timed out", b.name)
            f.cancel()

        return results

    def shutdown(self) -> None:
        # wait=True ensures in-flight writes are not lost on shutdown
        self._pool.shutdown(wait=True)
