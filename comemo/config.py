from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HonchoConfig:
    enabled: bool = False
    api_key: str = ""
    workspace: str = "hermes"
    base_url: str = "https://api.honcho.dev"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HonchoConfig:
        api_key = d.get("api_key") or os.environ.get("HONCHO_API_KEY", "")
        return cls(
            enabled=bool(d.get("enabled", bool(api_key))),
            api_key=api_key,
            workspace=d.get("workspace", "hermes"),
            base_url=d.get("base_url", "https://api.honcho.dev"),
        )


@dataclass
class Mem0Config:
    enabled: bool = False
    api_key: str = ""
    user_id: str = "hermes-user"
    agent_id: str = "hermes"
    base_url: str = ""  # non-empty enables OSS / self-hosted mode

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Mem0Config:
        api_key = d.get("api_key") or os.environ.get("MEM0_API_KEY", "")
        return cls(
            enabled=bool(d.get("enabled", bool(api_key))),
            api_key=api_key,
            user_id=d.get("user_id", "hermes-user"),
            agent_id=d.get("agent_id", "hermes"),
            base_url=d.get("base_url") or os.environ.get("MEM0_BASE_URL", ""),
        )


@dataclass
class SupermemoryConfig:
    enabled: bool = False
    api_key: str = ""
    namespace: str = "hermes"
    base_url: str = "https://api.supermemory.ai"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SupermemoryConfig:
        api_key = d.get("api_key") or os.environ.get("SUPERMEMORY_API_KEY", "")
        return cls(
            enabled=bool(d.get("enabled", bool(api_key))),
            api_key=api_key,
            namespace=d.get("namespace", "hermes"),
            base_url=d.get("base_url", "https://api.supermemory.ai"),
        )


@dataclass
class ComemoConfig:
    honcho: HonchoConfig = field(default_factory=HonchoConfig)
    mem0: Mem0Config = field(default_factory=Mem0Config)
    supermemory: SupermemoryConfig = field(default_factory=SupermemoryConfig)
    fan_out_timeout: float = 5.0
    min_backends: int = 1

    @classmethod
    def load(cls, raw: dict[str, Any] | None = None) -> ComemoConfig:
        d = raw or {}
        return cls(
            honcho=HonchoConfig.from_dict(d.get("honcho") or {}),
            mem0=Mem0Config.from_dict(d.get("mem0") or {}),
            supermemory=SupermemoryConfig.from_dict(d.get("supermemory") or {}),
            fan_out_timeout=float(d.get("fan_out_timeout", 5.0)),
            min_backends=int(d.get("min_backends", 1)),
        )
