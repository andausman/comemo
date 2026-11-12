from __future__ import annotations

import os
import sys
import tempfile
from typing import Any


def _read_secret(name: str) -> str:
    try:
        from agent.secret_scope import get_secret
        return get_secret(name) or ""
    except Exception:
        return os.environ.get(name, "")


def _hermes_home() -> str:
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home()
    except Exception:
        return os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def _hermes_config_path() -> str:
    return os.path.join(_hermes_home(), "config.yaml")


def _load_yaml(path: str) -> dict[str, Any]:
    import yaml
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _save_yaml(path: str, data: dict[str, Any]) -> None:
    import yaml
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)




def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    if secret and default:
        suffix = "  [******** — press Enter to keep]"
    elif secret:
        suffix = "  (hidden)"
    elif default:
        suffix = f" [{default}]"
    else:
        suffix = ""
    try:
        if secret:
            import getpass
            value = getpass.getpass(f"  {prompt}{suffix}: ").strip()
            result = value or default
            if result:
                print(f"  {'(kept)' if not value and default else '(set)'}")
            return result
        else:
            value = input(f"  {prompt}{suffix}: ").strip()
            return value or default
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def _ask_bool(prompt: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        value = input(f"  {prompt} {hint}: ").strip().lower()
        return (value in ("y", "yes")) if value else default
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def _ping(endpoint: str) -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(endpoint, timeout=2)
        return True
    except Exception:
        return False


def _detect_native_configs() -> dict[str, str]:
    found: dict[str, str] = {}
    for env_var, cfg_key in [
        ("HONCHO_API_KEY",      "honcho_api_key"),
        ("MEM0_API_KEY",        "mem0_api_key"),
        ("SUPERMEMORY_API_KEY", "supermemory_api_key"),
        ("HINDSIGHT_API_KEY",   "hindsight_api_key"),
    ]:
        key = _read_secret(env_var)
        if key:
            found[cfg_key] = key
    return found


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="hermes-comemo")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="Configure memory providers")
    subparsers.add_parser("status", help="Show configured providers and their state")
    subparsers.add_parser("test", help="Test live connectivity to each provider")
    inspect_p = subparsers.add_parser("inspect", help="Query all providers and show stored memories")
    inspect_p.add_argument("--query", default="", help="Search query (default: broad recall of all memories)")
    inspect_p.add_argument("--limit", type=int, default=20, help="Max entries per provider (default: 20)")
    subparsers.add_parser("help", help="Show this help message")
    args = parser.parse_args()
    if args.command == "setup":
        run()
    elif args.command == "status":
        status()
    elif args.command == "test":
        test()
    elif args.command == "inspect":
        inspect(query=args.query, limit=args.limit)
    else:
        parser.print_help()


def status() -> None:
    from .config import ComemoConfig

    config_path = _hermes_config_path()
    cfg_raw = _load_yaml(config_path)
    provider = cfg_raw.get("memory", {}).get("provider", "")
    comemo = cfg_raw.get("plugins", {}).get("comemo", {})

    print(f"\ncomemo  ({config_path})")
    if provider != "comemo":
        print(f"  Warning: memory.provider is '{provider}', not 'comemo' — run setup to fix")
    print()

    if not comemo:
        print("  No comemo config found. Run: hermes comemo setup")
        print()
        return

    cfg = ComemoConfig.load(comemo)

    rows = [
        ("honcho",      cfg.honcho.enabled,      cfg.honcho.api_key,      f"workspace={cfg.honcho.workspace}"),
        ("mem0",        cfg.mem0.enabled,         cfg.mem0.api_key,        f"user_id={cfg.mem0.user_id}"),
        ("supermemory", cfg.supermemory.enabled,  cfg.supermemory.api_key, f"namespace={cfg.supermemory.namespace}"),
    ]

    for name, enabled, key, detail in rows:
        if not enabled:
            print(f"  {name:<12} disabled")
        elif not key:
            print(f"  {name:<12} enabled   (no API key — will be skipped at runtime)")
        else:
            print(f"  {name:<12} enabled   {detail}")
    print()


def test() -> None:
    import time
    import uuid
    from .backends.hindsight import HindsightBackend
    from .backends.honcho import HonchoBackend
    from .backends.mem0 import Mem0Backend
    from .backends.supermemory import SupermemoryBackend
    from .config import ComemoConfig

    config_path = _hermes_config_path()
    raw = _load_yaml(config_path).get("plugins", {}).get("comemo", {})
    cfg = ComemoConfig.load(raw) if raw else ComemoConfig()

    # Realistic multi-turn conversation — simulates actual Hermes usage.
    # Uses a unique marker so we can verify the write landed in recall.
    marker = f"comemo-test-{uuid.uuid4().hex[:8]}"
    session_id = f"comemo-test-session-{uuid.uuid4().hex[:6]}"

    conversation = [
        (
            f"My name is TestUser and I'm evaluating memory providers. My marker is {marker}.",
            "Got it — I'll remember you're TestUser evaluating memory providers.",
        ),
        (
            "I prefer providers that support cross-session recall over session-only storage.",
            "Noted — cross-session recall is your priority over session-only storage.",
        ),
        (
            "I'm building a Hermes plugin called comemo that multiplexes multiple providers.",
            "Understood — you're building comemo, a composite memory provider for Hermes.",
        ),
    ]
    recall_query = "TestUser memory provider preferences"
    # At least one of these must appear in recall for the round-trip to pass
    recall_signals = [marker, "TestUser", "cross-session", "comemo"]

    backends = [
        HonchoBackend(cfg.honcho),
        Mem0Backend(cfg.mem0),
        SupermemoryBackend(cfg.supermemory),
        HindsightBackend(cfg.hindsight),
    ]

    print(f"\ntesting Comemo providers  (session: {session_id})\n")

    for b in backends:
        if not b.is_available():
            print(f"  {b.name:<12} SKIP   not enabled or unavailable")
            continue

        # --- initialize ---
        try:
            with tempfile.TemporaryDirectory() as tmp:
                b.initialize(session_id, tmp)
        except Exception as exc:
            print(f"  {b.name:<12} FAIL   initialize: {exc}")
            continue

        # --- write (multi-turn) ---
        write_errors: list[str] = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                b.initialize(session_id, tmp)
                for user_msg, assistant_msg in conversation:
                    try:
                        b.sync_turn(user_msg, assistant_msg, session_id=session_id)
                    except Exception as exc:
                        write_errors.append(str(exc))
                b.on_session_end([])
                b.shutdown()
        except Exception as exc:
            print(f"  {b.name:<12} FAIL   write: {exc}")
            continue

        if write_errors:
            print(f"  {b.name:<12} WARN   {len(write_errors)} write error(s): {write_errors[0]}")

        # --- indexing delay (most providers async-index) ---
        time.sleep(3)

        # --- recall (new session — simulates cross-session memory) ---
        recall_session = f"comemo-test-recall-{uuid.uuid4().hex[:6]}"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                b.initialize(recall_session, tmp)
                result = b.prefetch(recall_query, session_id=recall_session)
                b.shutdown()
        except Exception as exc:
            print(f"  {b.name:<12} WARN   write OK, recall failed: {exc}")
            continue

        found = [s for s in recall_signals if s.lower() in result.lower()]
        if not result.strip():
            status = "WARN   write OK, recall returned nothing (indexing lag or provider delay?)"
        elif not found:
            status = f"WARN   write OK, recall returned content but expected signals not found"
        else:
            status = f"OK     write + recall  (found: {', '.join(found)})"

        print(f"  {b.name:<12} {status}")

    print()
    print(f"  Test data written under session '{session_id}'.")
    print(f"  Run 'hermes comemo inspect --query \"{marker}\"' to see what was stored.")
    print()


def inspect(query: str = " ", limit: int = 20) -> None:
    import tempfile
    from .backends.hindsight import HindsightBackend
    from .backends.honcho import HonchoBackend
    from .backends.mem0 import Mem0Backend
    from .backends.supermemory import SupermemoryBackend
    from .config import ComemoConfig

    config_path = _hermes_config_path()
    raw = _load_yaml(config_path).get("plugins", {}).get("comemo", {})
    cfg = ComemoConfig.load(raw) if raw else ComemoConfig()

    label = repr(query) if query.strip() else "(all memories)"
    print(f"\ninspecting Comemo providers  (query: {label}, limit: {limit})\n")

    backends = [
        HonchoBackend(cfg.honcho),
        Mem0Backend(cfg.mem0),
        SupermemoryBackend(cfg.supermemory),
        HindsightBackend(cfg.hindsight),
    ]

    for b in backends:
        if not b.is_available():
            print(f"  {b.name:<12} SKIP   not enabled or unavailable")
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                b.initialize("comemo-inspect", tmp)
                result = b.prefetch(query, session_id="comemo-inspect")
                b.shutdown()
            entries = [line for line in result.split("\n") if line.strip()][:limit]
            if not entries:
                print(f"  {b.name:<12} (no results)")
            else:
                print(f"  {b.name}  ({len(entries)} entries)")
                for i, line in enumerate(entries, 1):
                    print(f"    [{i}] {line}")
        except Exception as exc:
            print(f"  {b.name:<12} ERROR  {exc}")
        print()


def _merge_known(detected: dict[str, str], existing: dict[str, Any]) -> dict[str, str]:
    # existing comemo config takes priority over native provider files
    merged = dict(detected)
    for provider, cfg in existing.items():
        if not isinstance(cfg, dict):
            continue
        key = cfg.get("api_key", "")
        if key:
            merged[f"{provider}_api_key"] = key
        for field in ("workspace", "user_id", "namespace", "base_url", "endpoint", "account", "user", "project"):
            val = cfg.get(field, "")
            if val:
                merged[f"{provider}_{field}"] = val
    return merged


def run() -> None:
    _banner()

    config_path = _hermes_config_path()
    existing_comemo = _load_yaml(config_path).get("plugins", {}).get("comemo", {})
    is_reconfigure = bool(existing_comemo)

    detected = _detect_native_configs()
    # Existing comemo config takes priority over native provider files
    detected = _merge_known(detected, existing_comemo)

    if is_reconfigure:
        from .config import ComemoConfig
        active_cfg = ComemoConfig.load(existing_comemo)
        active_now = [
            name for name, enabled in [
                ("honcho", active_cfg.honcho.enabled),
                ("mem0", active_cfg.mem0.enabled),
                ("supermemory", active_cfg.supermemory.enabled),
                ("hindsight", active_cfg.hindsight.enabled),
            ] if enabled
        ]
        print(f"  Existing config found — currently active: {', '.join(active_now) or 'none'}")
        print("  Press Enter on each prompt to keep current values.\n")
    comemo_cfg: dict[str, Any] = {}

    # --- Honcho ---
    print("Honcho  (peer-based persistent user modeling)")
    print("  Tracks who you are across sessions. Get a key at honcho.dev")
    existing_key = detected.get("honcho_api_key", "")
    currently_enabled = (ComemoConfig.load(existing_comemo).honcho.enabled) if is_reconfigure else bool(existing_key)
    if _ask_bool("Enable Honcho?", default=currently_enabled):
        workspace = _ask("Workspace", default=detected.get("honcho_workspace", "hermes"))
        comemo_cfg["honcho"] = {"enabled": True, "workspace": workspace}
    print()

    # --- Mem0 ---
    print("Mem0  (fact extraction via LLM + semantic retrieval)")
    print("  Automatically pulls facts from conversations. Get a key at mem0.ai")
    existing_key = detected.get("mem0_api_key", "")
    currently_enabled = (ComemoConfig.load(existing_comemo).mem0.enabled) if is_reconfigure else bool(existing_key)
    if _ask_bool("Enable Mem0?", default=currently_enabled):
        user_id = _ask("User ID", default=detected.get("mem0_user_id", "hermes-user"))
        comemo_cfg["mem0"] = {"enabled": True, "user_id": user_id}
    print()

    # --- Supermemory ---
    print("Supermemory  (3-layer retrieval: profile + entity graph + document RAG)")
    print("  Get a key at console.supermemory.ai  or run 'npx supermemory local' for self-hosted")
    existing_key = detected.get("supermemory_api_key", "")
    currently_enabled = (ComemoConfig.load(existing_comemo).supermemory.enabled) if is_reconfigure else bool(existing_key)
    if _ask_bool("Enable Supermemory?", default=currently_enabled):
        namespace = _ask("Namespace", default=detected.get("supermemory_namespace", "hermes"))
        print("  Tip: use a unique namespace per Hermes profile to keep memory isolated.")
        comemo_cfg["supermemory"] = {"enabled": True, "namespace": namespace}
    print()

    # --- Hindsight ---
    print("Hindsight  (vectorized knowledge graph + entity resolution)")
    print("  Stores memories as a graph with entity linking. Get a key at hindsight.so")
    existing_key = detected.get("hindsight_api_key", "")
    currently_enabled = (ComemoConfig.load(existing_comemo).hindsight.enabled) if is_reconfigure else bool(existing_key)
    if _ask_bool("Enable Hindsight?", default=currently_enabled):
        bank_id = _ask("Bank ID", default=detected.get("hindsight_bank_id", ""))
        comemo_cfg["hindsight"] = {"enabled": True, "bank_id": bank_id}
    print()

    active = [k for k, v in comemo_cfg.items() if isinstance(v, dict) and v.get("enabled")]
    if not active:
        print("No providers configured. Nothing written.")
        print("Run hermes comemo setup again when you have at least one API key ready.")
        print()
        return

    try:
        from hermes_cli.config import load_config, save_config as _save_cfg
        cfg = load_config()
        cfg.setdefault("plugins", {})["comemo"] = comemo_cfg
        _save_cfg(cfg)
        print(f"Config written to {_hermes_config_path()}")
    except Exception as exc:
        print(f"Could not write config ({exc})")
        print()
        print("Add this block to your Hermes config.yaml manually:")
        print()
        _print_manual_block(comemo_cfg)
        return

    print(f"Active providers: {', '.join(active)}")
    print()

    # resolves deps and builds the plugin venv; best-effort — config.yaml is enough if hermes isn't on PATH
    try:
        import subprocess
        result = subprocess.run(
            ["hermes", "plugins", "enable", "comemo"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            print("Plugin enabled via hermes plugins enable.")
        else:
            print("Warning: hermes plugins enable comemo failed:")
            for line in (result.stdout + result.stderr).splitlines()[-6:]:
                print(f"  {line}")
            print("Run 'hermes plugins enable comemo' manually after fixing the error above.")
    except FileNotFoundError:
        pass  # hermes CLI not on PATH — config.yaml is enough for manual installs
    except Exception as exc:
        print(f"Warning: could not run hermes plugins enable — {exc}")

    print()
    print("Run 'hermes memory setup' to set your API keys, then start a new session.")
    print()


def _banner() -> None:
    print()
    print("Comemo — Composite Memory Meta-Provider")
    print("=" * 42)
    print()
    print("Comemo multiplexes multiple Hermes memory providers simultaneously.")
    print("Each provider you enable runs in parallel — reads and writes fan out to all of them.")
    print()


def _print_manual_block(comemo_cfg: dict[str, Any]) -> None:
    import yaml
    block = {"plugins": {"comemo": comemo_cfg}}
    print(yaml.dump(block, default_flow_style=False, sort_keys=False))
    print("Then run: hermes plugins enable comemo")
    print("And run:  hermes memory setup  (to set API keys)")
