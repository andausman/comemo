from __future__ import annotations

import logging
import os
from typing import Any

from .adapters.hermes import HermesAdapter
from .config import ComemoConfig

__version__ = "1.0.0"
__all__ = ["register"]

logger = logging.getLogger(__name__)


def _load_raw_cfg_from_file() -> dict[str, Any]:
    import yaml
    try:
        from hermes_constants import get_hermes_home
        hermes_home = get_hermes_home()
    except Exception:
        hermes_home = os.path.expanduser("~/.hermes")
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
