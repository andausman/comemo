from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any

from .adapters.hermes import HermesAdapter
from .config import ComemoConfig

__version__ = "1.0.0"
__all__ = ["register"]

logger = logging.getLogger(__name__)

_BACKEND_PACKAGES = [
    ("honcho",      "honcho",      "honcho-ai"),
    ("mem0",        "mem0",        "mem0ai"),
    ("supermemory", "supermemory", "supermemory"),
]


def _auto_install_missing(cfg: "ComemoConfig") -> None:
    enabled = {
        "honcho":      cfg.honcho.enabled and bool(cfg.honcho.api_key),
        "mem0":        cfg.mem0.enabled and bool(cfg.mem0.api_key),
        "supermemory": cfg.supermemory.enabled and bool(cfg.supermemory.api_key),
    }
    for name, import_name, pip_name in _BACKEND_PACKAGES:
        if not enabled.get(name):
            continue
        try:
            __import__(import_name)
        except ImportError:
            logger.info("comemo: %s not found — installing %s ...", name, pip_name)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pip_name],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                logger.info("comemo: %s installed", pip_name)
            else:
                logger.warning("comemo: could not install %s: %s", pip_name, result.stderr.strip())
                logger.debug("comemo: pip install %s stderr: %s", pip_name, result.stderr[:200])


def _load_raw_cfg_from_file() -> dict[str, Any]:
    import yaml
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    config_path = os.path.join(hermes_home, "config.yaml")
    try:
        with open(config_path) as f:
            return (yaml.safe_load(f) or {}).get("plugins", {}).get("comemo", {})
    except Exception:
        logger.debug("comemo: config load failed, using defaults")
        return {}


def register(ctx: Any) -> None:
    # ctx.get_config only exists on bundled ctx — user plugin ctx falls back to config.yaml
    get_config = getattr(ctx, "get_config", None)

    if callable(get_config):
        raw_cfg: dict[str, Any] = {
            "honcho": {
                "enabled": get_config("honcho.enabled", False),
                "api_key": get_config("honcho.api_key", ""),
                "workspace": get_config("honcho.workspace", "hermes"),
            },
            "mem0": {
                "enabled": get_config("mem0.enabled", False),
                "api_key": get_config("mem0.api_key", ""),
                "user_id": get_config("mem0.user_id", "hermes-user"),
            },
            "supermemory": {
                "enabled": get_config("supermemory.enabled", False),
                "api_key": get_config("supermemory.api_key", ""),
                "namespace": get_config("supermemory.namespace", "hermes"),
            },
            "fan_out_timeout": get_config("fan_out_timeout", 5.0),
        }
    else:
        raw_cfg = _load_raw_cfg_from_file()

    cfg = ComemoConfig.load(raw_cfg)

    # auto-install in case hermes runs in a different venv than the install venv
    _auto_install_missing(cfg)

    data_dir: str | None = None
    try:
        data_dir = ctx.plugin_data_dir("comemo")
    except (AttributeError, TypeError):
        pass

    # Register CLI commands first — setup/status must work even before any provider is configured
    try:
        from .cli import register_cli, _dispatch
        ctx.register_cli_command(
            name="comemo",
            help="Manage comemo memory providers",
            setup_fn=register_cli,
            handler_fn=_dispatch,
        )
        logger.info("comemo: CLI commands registered")
    except Exception as exc:
        logger.debug("comemo: CLI registration skipped: %s", exc)

    adapter = HermesAdapter(cfg, data_dir=data_dir)
    if not adapter.is_available():
        logger.warning(
            "comemo: no providers available — enable at least one provider "
            "(honcho, mem0, or supermemory) under plugins.comemo in config.yaml"
        )
        return

    ctx.register_memory_provider(adapter)
    logger.info("comemo: memory provider registered")
