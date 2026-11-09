"""Unit tests for hermes-comemo. No external backend dependencies."""
from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from comemo.config import (
    ComemoConfig,
    HonchoConfig,
    Mem0Config,
    SupermemoryConfig,
)
from comemo.core import ComemoCore
from comemo.fanout import FanOut
from comemo.retry import RetryQueue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_BACKEND_NAMES = ["honcho", "mem0", "supermemory"]


def _mock_backend(name: str, available: bool = True, prefetch_result: str = "") -> MagicMock:
    m = MagicMock()
    m.name = name
    m.is_available.return_value = available
    m.prefetch.return_value = prefetch_result or f"memory from {name}"
    m.sync_turn.return_value = None
    return m


def _make_core(available: list[str] | None = None) -> ComemoCore:
    """Return a ComemoCore whose backends are all mocks."""
    cfg = ComemoConfig(
        honcho=HonchoConfig(enabled=True, api_key="hc_test"),
        mem0=Mem0Config(enabled=True, api_key="m0_test"),
        supermemory=SupermemoryConfig(enabled=True, api_key="sm_test"),
    )
    core = ComemoCore(cfg)
    mocks = [
        _mock_backend(name, available=(available is None or name in available))
        for name in ALL_BACKEND_NAMES
    ]
    core._build_backends = lambda: mocks  # type: ignore[method-assign]
    return core


# ---------------------------------------------------------------------------
# Config — loading and defaults
# ---------------------------------------------------------------------------

class TestComemoConfig:

    def test_load_empty_defaults(self) -> None:
        cfg = ComemoConfig.load({})
        assert cfg.fan_out_timeout == 5.0
        assert cfg.min_backends == 1
        assert not cfg.honcho.enabled
        assert not cfg.mem0.enabled
        assert not cfg.supermemory.enabled

    def test_load_honcho(self) -> None:
        cfg = ComemoConfig.load({"honcho": {"enabled": True, "api_key": "hc_x", "workspace": "myapp"}})
        assert cfg.honcho.enabled
        assert cfg.honcho.api_key == "hc_x"
        assert cfg.honcho.workspace == "myapp"
        assert not cfg.mem0.enabled

    def test_load_mem0(self) -> None:
        cfg = ComemoConfig.load({"mem0": {"enabled": True, "api_key": "m0_x", "user_id": "alice"}})
        assert cfg.mem0.enabled
        assert cfg.mem0.api_key == "m0_x"
        assert cfg.mem0.user_id == "alice"

    def test_load_supermemory(self) -> None:
        cfg = ComemoConfig.load({
            "supermemory": {"enabled": True, "api_key": "sm_x", "namespace": "myns", "base_url": "http://localhost:6767"}
        })
        assert cfg.supermemory.enabled
        assert cfg.supermemory.api_key == "sm_x"
        assert cfg.supermemory.namespace == "myns"
        assert cfg.supermemory.base_url == "http://localhost:6767"

    def test_load_fan_out_timeout(self) -> None:
        cfg = ComemoConfig.load({"fan_out_timeout": 2.5})
        assert cfg.fan_out_timeout == 2.5

    def test_honcho_defaults(self) -> None:
        cfg = HonchoConfig.from_dict({})
        assert cfg.workspace == "hermes"
        assert cfg.base_url == "https://api.honcho.dev"

    def test_mem0_defaults(self) -> None:
        cfg = Mem0Config.from_dict({})
        assert cfg.user_id == "hermes-user"

    def test_supermemory_defaults(self) -> None:
        cfg = SupermemoryConfig.from_dict({})
        assert cfg.namespace == "hermes"
        assert cfg.base_url == "https://api.supermemory.ai"

    def test_env_var_honcho(self) -> None:
        with patch.dict(os.environ, {"HONCHO_API_KEY": "env_hc_key"}):
            cfg = HonchoConfig.from_dict({"enabled": True})
            assert cfg.api_key == "env_hc_key"

    def test_env_var_mem0(self) -> None:
        with patch.dict(os.environ, {"MEM0_API_KEY": "env_m0_key"}):
            cfg = Mem0Config.from_dict({"enabled": True})
            assert cfg.api_key == "env_m0_key"

    def test_env_var_supermemory(self) -> None:
        with patch.dict(os.environ, {"SUPERMEMORY_API_KEY": "env_sm_key"}):
            cfg = SupermemoryConfig.from_dict({"enabled": True})
            assert cfg.api_key == "env_sm_key"

    def test_explicit_key_overrides_env(self) -> None:
        with patch.dict(os.environ, {"HONCHO_API_KEY": "env_key"}):
            cfg = HonchoConfig.from_dict({"enabled": True, "api_key": "explicit_key"})
            assert cfg.api_key == "explicit_key"


# ---------------------------------------------------------------------------
# ComemoCore — availability
# ---------------------------------------------------------------------------

class TestCoreAvailability:

    def test_available_when_at_least_one_backend_ready(self) -> None:
        core = _make_core(["honcho"])
        assert core.is_available()

    def test_available_with_multiple_backends(self) -> None:
        core = _make_core(["mem0", "supermemory"])
        assert core.is_available()

    def test_not_available_when_no_backends(self) -> None:
        core = _make_core([])
        assert not core.is_available()

    def test_name_is_comemo(self) -> None:
        assert ComemoCore().name == "comemo"

    def test_active_backend_names_empty_before_init(self) -> None:
        core = _make_core(["honcho"])
        assert core.active_backend_names == []


# ---------------------------------------------------------------------------
# ComemoCore — initialize
# ---------------------------------------------------------------------------

class TestCoreInitialize:

    def test_active_backends_populated_after_init(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("sess-1", str(tmp_path))
        assert set(core.active_backend_names) == {"honcho", "mem0"}

    def test_unavailable_backends_excluded(self, tmp_path: Any) -> None:
        core = _make_core(["supermemory"])
        core.initialize("sess-1", str(tmp_path))
        assert core.active_backend_names == ["supermemory"]

    def test_failed_initialize_removes_backend(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "supermemory"])
        core.initialize("sess-1", str(tmp_path))
        # Simulate honcho failing during initialize by patching after the fact
        # (re-initialize with a backend that raises)
        core2 = _make_core(["honcho", "supermemory"])
        mocks = core2._build_backends()
        for b in mocks:
            if b.name == "honcho":
                b.initialize.side_effect = RuntimeError("network error")
        core2._build_backends = lambda: mocks  # type: ignore[method-assign]
        core2.initialize("sess-2", str(tmp_path))
        assert "honcho" not in core2.active_backend_names
        assert "supermemory" in core2.active_backend_names

    def test_all_backends_initialized(self, tmp_path: Any) -> None:
        core = _make_core()
        core.initialize("sess-1", str(tmp_path))
        assert len(core.active_backend_names) == 3

    def test_retry_queue_created(self, tmp_path: Any) -> None:
        core = _make_core(["honcho"])
        core.initialize("sess-1", str(tmp_path))
        assert core._retry is not None


# ---------------------------------------------------------------------------
# ComemoCore — read (prefetch)
# ---------------------------------------------------------------------------

class TestCoreRead:

    def test_merges_results_from_all_backends(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0", "supermemory"])
        core.initialize("sess-1", str(tmp_path))
        result = core.read("what do I like?", session_id="sess-1")
        assert "memory from honcho" in result
        assert "memory from mem0" in result
        assert "memory from supermemory" in result

    def test_deduplicates_identical_lines(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("sess-1", str(tmp_path))
        for b in core._backends:
            b.prefetch.return_value = "user prefers dark mode"
        result = core.read("preferences")
        assert result.count("user prefers dark mode") == 1

    def test_returns_empty_when_no_backends(self) -> None:
        core = ComemoCore()
        assert core.read("anything") == ""

    def test_empty_lines_filtered(self, tmp_path: Any) -> None:
        core = _make_core(["honcho"])
        core.initialize("sess-1", str(tmp_path))
        core._backends[0].prefetch.return_value = "line one\n\n   \nline two"
        result = core.read("q")
        assert "line one" in result
        assert "line two" in result
        assert result.count("\n") == 1  # only one separator between two lines

    def test_failed_prefetch_returns_partial_results(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("sess-1", str(tmp_path))
        core._backends[0].prefetch.return_value = "good result"
        core._backends[1].prefetch.side_effect = RuntimeError("timeout")
        # Should not raise — just return what succeeded
        result = core.read("q")
        assert "good result" in result

    def test_system_prompt_block_lists_active_backends(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("sess-1", str(tmp_path))
        block = core.system_prompt_block()
        assert "honcho" in block
        assert "mem0" in block

    def test_system_prompt_block_empty_when_no_backends(self) -> None:
        core = ComemoCore()
        assert core.system_prompt_block() == ""


# ---------------------------------------------------------------------------
# ComemoCore — write (sync_turn)
# ---------------------------------------------------------------------------

class TestCoreWrite:

    def test_fans_out_to_all_active_backends(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0", "supermemory"])
        core.initialize("sess-1", str(tmp_path))
        core.write("hello", "hi there", session_id="sess-1")
        for b in core._backends:
            b.sync_turn.assert_called_once_with("hello", "hi there", session_id="sess-1")

    def test_failed_write_queued_for_retry(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("sess-1", str(tmp_path))
        for b in core._backends:
            if b.name == "honcho":
                b.sync_turn.side_effect = RuntimeError("timeout")
        core.write("hi", "hello", session_id="sess-1")
        assert core._retry is not None
        pending = core._retry.drain()
        assert any(item["backend"] == "honcho" for item in pending)

    def test_successful_write_not_queued(self, tmp_path: Any) -> None:
        core = _make_core(["mem0"])
        core.initialize("sess-1", str(tmp_path))
        core.write("hi", "hello", session_id="sess-1")
        assert core._retry is not None
        assert core._retry.drain() == []

    def test_write_no_op_when_no_backends(self) -> None:
        core = ComemoCore()
        core.write("hi", "hello")  # should not raise

    def test_write_passes_session_id(self, tmp_path: Any) -> None:
        core = _make_core(["mem0"])
        core.initialize("s", str(tmp_path))
        core.write("u", "a", session_id="my-session")
        core._backends[0].sync_turn.assert_called_once_with("u", "a", session_id="my-session")


# ---------------------------------------------------------------------------
# ComemoCore — session lifecycle hooks
# ---------------------------------------------------------------------------

class TestCoreLifecycle:

    def test_on_session_end_called_on_all_backends(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("s", str(tmp_path))
        msgs: list[Any] = [{"role": "user", "content": "hi"}]
        core.on_session_end(msgs)
        for b in core._backends:
            b.on_session_end.assert_called_once_with(msgs)

    def test_on_pre_compress_called_on_all_backends(self, tmp_path: Any) -> None:
        core = _make_core(["supermemory"])
        core.initialize("s", str(tmp_path))
        msgs: list[Any] = []
        core.on_pre_compress(msgs)
        core._backends[0].on_pre_compress.assert_called_once_with(msgs)

    def test_shutdown_called_on_all_backends(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("s", str(tmp_path))
        core.shutdown()
        for b in core._backends:
            b.shutdown.assert_called_once()

    def test_on_session_end_survives_backend_error(self, tmp_path: Any) -> None:
        core = _make_core(["honcho", "mem0"])
        core.initialize("s", str(tmp_path))
        core._backends[0].on_session_end.side_effect = RuntimeError("boom")
        core.on_session_end([])  # should not raise


# ---------------------------------------------------------------------------
# Individual backend — is_available()
# ---------------------------------------------------------------------------

class TestBackendAvailability:

    def test_honcho_disabled(self) -> None:
        from comemo.backends.honcho import HonchoBackend
        b = HonchoBackend(HonchoConfig(enabled=False, api_key="hc_x"))
        assert not b.is_available()

    def test_honcho_no_key(self) -> None:
        from comemo.backends.honcho import HonchoBackend
        b = HonchoBackend(HonchoConfig(enabled=True, api_key=""))
        assert not b.is_available()

    def test_honcho_available_when_package_present(self) -> None:
        from comemo.backends.honcho import HonchoBackend
        with patch.dict("sys.modules", {"honcho": MagicMock()}):
            b = HonchoBackend(HonchoConfig(enabled=True, api_key="hc_x"))
            assert b.is_available()

    def test_honcho_unavailable_when_package_missing(self) -> None:
        from comemo.backends.honcho import HonchoBackend
        with patch.dict("sys.modules", {"honcho": None}):
            b = HonchoBackend(HonchoConfig(enabled=True, api_key="hc_x"))
            assert not b.is_available()

    def test_mem0_disabled(self) -> None:
        from comemo.backends.mem0 import Mem0Backend
        b = Mem0Backend(Mem0Config(enabled=False, api_key="m0_x"))
        assert not b.is_available()

    def test_mem0_no_key(self) -> None:
        from comemo.backends.mem0 import Mem0Backend
        b = Mem0Backend(Mem0Config(enabled=True, api_key=""))
        assert not b.is_available()

    def test_mem0_available_when_package_present(self) -> None:
        from comemo.backends.mem0 import Mem0Backend
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            b = Mem0Backend(Mem0Config(enabled=True, api_key="m0_x"))
            assert b.is_available()

    def test_supermemory_disabled(self) -> None:
        from comemo.backends.supermemory import SupermemoryBackend
        b = SupermemoryBackend(SupermemoryConfig(enabled=False, api_key="sm_x"))
        assert not b.is_available()

    def test_supermemory_no_key(self) -> None:
        from comemo.backends.supermemory import SupermemoryBackend
        b = SupermemoryBackend(SupermemoryConfig(enabled=True, api_key=""))
        assert not b.is_available()

    def test_supermemory_available_when_package_present(self) -> None:
        from comemo.backends.supermemory import SupermemoryBackend
        with patch.dict("sys.modules", {"supermemory": MagicMock()}):
            b = SupermemoryBackend(SupermemoryConfig(enabled=True, api_key="sm_x"))
            assert b.is_available()


# ---------------------------------------------------------------------------
# Individual backend — prefetch returns empty on failure (not raise)
# ---------------------------------------------------------------------------

class TestBackendPrefetchSafety:

    def test_honcho_prefetch_returns_empty_on_error(self) -> None:
        from comemo.backends.honcho import HonchoBackend
        b = HonchoBackend(HonchoConfig(enabled=True, api_key="hc_x"))
        mock_client = MagicMock()
        mock_client.peer.return_value.search.side_effect = RuntimeError("network")
        b._client = mock_client
        assert b.prefetch("query") == ""

    def test_mem0_prefetch_returns_empty_on_error(self) -> None:
        from comemo.backends.mem0 import Mem0Backend
        b = Mem0Backend(Mem0Config(enabled=True, api_key="m0_x"))
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("timeout")
        b._client = mock_client
        assert b.prefetch("query") == ""

    def test_supermemory_prefetch_returns_empty_on_error(self) -> None:
        from comemo.backends.supermemory import SupermemoryBackend
        b = SupermemoryBackend(SupermemoryConfig(enabled=True, api_key="sm_x"))
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("api error")
        b._client = mock_client
        assert b.prefetch("query") == ""


# ---------------------------------------------------------------------------
# Individual backend — prefetch result parsing
# ---------------------------------------------------------------------------

class TestBackendPrefetchParsing:

    def test_mem0_handles_dict_results(self) -> None:
        from comemo.backends.mem0 import Mem0Backend
        b = Mem0Backend(Mem0Config(enabled=True, api_key="m0_x"))
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"memory": "user likes Python"}, {"memory": "user is in Lagos"}]
        }
        b._client = mock_client
        result = b.prefetch("preferences")
        assert "user likes Python" in result
        assert "user is in Lagos" in result

    def test_mem0_handles_str_results(self) -> None:
        from comemo.backends.mem0 import Mem0Backend
        b = Mem0Backend(Mem0Config(enabled=True, api_key="m0_x"))
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": ["user likes Python", "user is in Lagos"]}
        b._client = mock_client
        result = b.prefetch("preferences")
        assert "user likes Python" in result

    def test_mem0_handles_empty_results(self) -> None:
        from comemo.backends.mem0 import Mem0Backend
        b = Mem0Backend(Mem0Config(enabled=True, api_key="m0_x"))
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        b._client = mock_client
        assert b.prefetch("q") == ""

    def test_honcho_extracts_content_attr(self) -> None:
        from comemo.backends.honcho import HonchoBackend
        b = HonchoBackend(HonchoConfig(enabled=True, api_key="hc_x"))
        r1 = MagicMock()
        r1.content = "user prefers TypeScript"
        r1.text = None
        mock_client = MagicMock()
        mock_client.peer.return_value.search.return_value = [r1]
        b._client = mock_client
        result = b.prefetch("style")
        assert "user prefers TypeScript" in result


    def test_supermemory_bucket_id_format(self) -> None:
        from comemo.backends.supermemory import SupermemoryBackend
        b = SupermemoryBackend(SupermemoryConfig(enabled=True, api_key="sm_x"))
        b._session_id = "test-session"
        bucket_id = b._bucket_id()
        # Format: {session_id}_{YYYYMMDD}_b{0-5}
        parts = bucket_id.split("_")
        assert parts[0] == "test-session"
        assert len(parts[1]) == 8  # YYYYMMDD
        assert parts[2].startswith("b")
        assert int(parts[2][1:]) in range(6)


# ---------------------------------------------------------------------------
# Retry queue
# ---------------------------------------------------------------------------

class TestRetryQueue:

    def test_push_and_drain(self, tmp_path: Any) -> None:
        q = RetryQueue(str(tmp_path / "retry.db"))
        q.push("mem0", "sync_turn", {"user": "hi", "assistant": "hello", "session_id": "s1"})
        items = q.drain()
        assert len(items) == 1
        assert items[0]["backend"] == "mem0"
        assert items[0]["op"] == "sync_turn"
        assert items[0]["payload"]["user"] == "hi"
        q.close()

    def test_ack_removes_item(self, tmp_path: Any) -> None:
        q = RetryQueue(str(tmp_path / "retry.db"))
        q.push("honcho", "sync_turn", {"user": "a", "assistant": "b", "session_id": ""})
        items = q.drain()
        q.ack(items[0]["id"])
        assert q.drain() == []
        q.close()

    def test_max_attempts_filters_items(self, tmp_path: Any) -> None:
        q = RetryQueue(str(tmp_path / "retry.db"))
        q.push("supermemory", "sync_turn", {"user": "x", "assistant": "y", "session_id": ""})
        items = q.drain()
        row_id = items[0]["id"]
        for _ in range(5):
            q.increment(row_id)
        assert q.drain() == []
        q.close()

    def test_multiple_backends_in_queue(self, tmp_path: Any) -> None:
        q = RetryQueue(str(tmp_path / "retry.db"))
        q.push("honcho", "sync_turn", {"user": "u", "assistant": "a", "session_id": ""})
        q.push("supermemory", "sync_turn", {"user": "u", "assistant": "a", "session_id": ""})
        items = q.drain()
        backends = {i["backend"] for i in items}
        assert backends == {"honcho", "supermemory"}
        q.close()

    def test_retry_replayed_on_initialize(self, tmp_path: Any) -> None:
        core = _make_core(["mem0"])
        core.initialize("sess-1", str(tmp_path))
        # Manually inject a pending item
        assert core._retry is not None
        core._retry.push("mem0", "sync_turn", {"user": "queued", "assistant": "ok", "session_id": "sess-1"})
        # Re-initialize — should replay
        core2 = _make_core(["mem0"])
        # Reuse the same retry db path
        from comemo.retry import RetryQueue as RQ
        core2._retry = RQ(str(tmp_path / "comemo-retry.db"))
        # Find the mem0 mock by name (index 0 is honcho)
        mem0_mock = next(m for m in core2._build_backends() if m.name == "mem0")
        core2._backends = [mem0_mock]
        core2._flush_retry_queue()
        mem0_mock.sync_turn.assert_called_once()


# ---------------------------------------------------------------------------
# FanOut
# ---------------------------------------------------------------------------

class TestFanOut:

    def _backends(self, n: int = 2) -> list[Any]:
        return [_mock_backend(f"b{i}") for i in range(n)]

    def test_write_calls_all_backends(self) -> None:
        backends = self._backends(3)
        fo = FanOut(backends, timeout=2.0)
        results = fo.write(backends, "sync_turn", "u", "a", session_id="s")
        assert all(exc is None for exc in results.values())
        for b in backends:
            b.sync_turn.assert_called_once_with("u", "a", session_id="s")
        fo.shutdown()

    def test_read_returns_result_per_backend(self) -> None:
        backends = self._backends(3)
        fo = FanOut(backends, timeout=2.0)
        results = fo.read(backends, "what do I like?")
        assert len(results) == 3
        fo.shutdown()

    def test_write_captures_exception(self) -> None:
        backends = self._backends(2)
        backends[0].sync_turn = MagicMock(side_effect=RuntimeError("boom"))
        backends[1].sync_turn = MagicMock(return_value=None)
        fo = FanOut(backends, timeout=2.0)
        results = fo.write(backends, "sync_turn", "u", "a", session_id="s")
        assert isinstance(results["b0"], RuntimeError)
        assert results["b1"] is None
        fo.shutdown()

    def test_read_drops_failed_backend(self) -> None:
        backends = self._backends(2)
        backends[0].prefetch.side_effect = RuntimeError("network error")
        backends[1].prefetch.return_value = "good result"
        fo = FanOut(backends, timeout=2.0)
        results = fo.read(backends, "q")
        # failed backend is dropped — only the successful result is returned
        assert results == ["good result"]
        fo.shutdown()

    def test_write_empty_backends_returns_empty_dict(self) -> None:
        fo = FanOut([], timeout=2.0)
        results = fo.write([], "sync_turn", "u", "a", session_id="s")
        assert results == {}
        fo.shutdown()

    def test_read_empty_backends_returns_empty_list(self) -> None:
        fo = FanOut([], timeout=2.0)
        results = fo.read([], "q")
        assert results == []
        fo.shutdown()


# ---------------------------------------------------------------------------
# HermesAdapter
# ---------------------------------------------------------------------------

class TestHermesAdapter:

    def test_name(self) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter()
        assert a.name == "comemo"

    def test_initialize_delegates_to_core(self, tmp_path: Any) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter(data_dir=str(tmp_path))
        # No backends active — should not raise
        a.initialize("sess-1", hermes_home=str(tmp_path))

    def test_prefetch_returns_string(self, tmp_path: Any) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter(data_dir=str(tmp_path))
        a.initialize("sess-1")
        result = a.prefetch("what do I like?")
        assert isinstance(result, str)

    def test_sync_turn_no_raise(self, tmp_path: Any) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter(data_dir=str(tmp_path))
        a.initialize("sess-1")
        a.sync_turn("hello", "hi there", session_id="sess-1")

    def test_get_config_schema_covers_all_providers(self) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter()
        schema = a.get_config_schema()
        keys = [s["key"] for s in schema]
        for provider in ("honcho", "mem0", "supermemory"):
            assert any(k.startswith(provider) for k in keys), f"missing {provider} in schema"

    def test_get_config_schema_no_chroma(self) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter()
        keys = [s["key"] for s in a.get_config_schema()]
        assert not any("chroma" in k for k in keys)

    def test_on_session_end_no_raise(self, tmp_path: Any) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter(data_dir=str(tmp_path))
        a.initialize("sess-1")
        a.on_session_end([{"role": "user", "content": "bye"}])

    def test_shutdown_no_raise(self, tmp_path: Any) -> None:
        from comemo.adapters.hermes import HermesAdapter
        a = HermesAdapter(data_dir=str(tmp_path))
        a.initialize("sess-1")
        a.shutdown()
