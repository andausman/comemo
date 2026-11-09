"""Hermes CLI extension: exposes 'hermes comemo <subcommand>' when the provider is active."""
from __future__ import annotations

from typing import Any


def register_cli(subparser: Any) -> None:
    subs = subparser.add_subparsers(dest="comemo_cmd")

    subs.add_parser("setup", help="Configure providers and API keys")
    subs.add_parser("status", help="Show configured providers")
    subs.add_parser("test", help="Test live connectivity to each provider")
    inspect_p = subs.add_parser("inspect", help="Query all providers and show stored memories")
    inspect_p.add_argument("--query", default="", help="Search query")
    inspect_p.add_argument("--limit", type=int, default=20, help="Max entries per provider")

    subparser.set_defaults(func=_dispatch)


def _dispatch(args: Any) -> None:
    from .wizard import run, status, test, inspect

    cmd = getattr(args, "comemo_cmd", None)
    if cmd == "setup":
        run()
    elif cmd == "status":
        status()
    elif cmd == "test":
        test()
    elif cmd == "inspect":
        inspect(query=getattr(args, "query", ""), limit=getattr(args, "limit", 20))
    else:
        print("Usage: hermes comemo <setup|status|test|inspect>")
