# Comemo

Comemo is a composite memory provider for Hermes Agent. It runs multiple memory providers at the same time instead of one.

Hermes lets you pick one memory provider. You can use Honcho, Mem0, or Supermemory, but only one at a time. Comemo sits in that single slot and writes to all of them at once. Reads come back merged and deduplicated. If one provider fails, the others keep running.

---

## The problem

The community built several memory providers for Hermes:

- **Honcho** - cloud memory that tracks who you are across sessions
- **Mem0** - reads every conversation and extracts facts automatically
- **Supermemory** - structured knowledge storage with semantic search

Hermes only activates one at a time. This is a known constraint ([Issue #24770](https://github.com/NousResearch/hermes-agent/issues/24770), marked wontfix in core). The maintainers asked the community to build a composite provider as a catalog plugin instead.

Comemo is that plugin.

---

## How it works

```
Your conversation
       |
       v
   [ Hermes ]
       |
       v
   [ Comemo ]  <-- implements MemoryProvider
       |
       +---> Honcho       (optional, cloud)
       +---> Mem0         (optional, cloud)
       +---> Supermemory  (optional, cloud)
```

On every write, Comemo fans out to all active providers in parallel using a thread pool. If a provider fails, the write goes into a local SQLite retry queue and replays at the next session start.

On every read, Comemo queries all active providers in parallel, merges the results, and deduplicates identical lines before returning to Hermes.

---

## Install

There are three install paths. Use the one that matches how you got Hermes.

---

### From the Hermes marketplace

```bash
hermes plugins install comemo
```

During install, Hermes prompts for each provider's API key. Press Enter to skip providers you don't want. Keys are saved to `~/.hermes/.env`.

Then run:

```bash
hermes memory setup
```

Select `comemo` when asked which provider to activate. This sets `memory.provider: comemo` in your config and walks through enabling each provider. Restart Hermes after and Comemo is live.

---

### From PyPI

```bash
pip install hermes-comemo
hermes-comemo setup
```

`pip install` puts `hermes-comemo` on your PATH. The `setup` wizard asks which providers to enable, prompts for API keys, and writes everything to `~/.hermes/config.yaml` and `~/.hermes/.env`.

Restart Hermes after setup and Comemo is live.

---

### From source

```bash
git clone https://github.com/andausman/comemo.git
cd comemo
hermes plugins install .
hermes memory setup
```

Or with pip:

```bash
git clone https://github.com/andausman/comemo.git
cd comemo
pip install -e .
hermes-comemo setup
```

---

## Setup

**After marketplace install:** run `hermes memory setup` — Hermes presents each field from the config schema and writes settings to `~/.hermes/config.yaml` and keys to `~/.hermes/.env`.

**After pip install:** run `hermes-comemo setup` — runs the full interactive wizard below.

### hermes-comemo setup wizard

```
Comemo — Composite Memory Meta-Provider
==========================================

Comemo multiplexes multiple Hermes memory providers simultaneously.
Each provider you enable runs in parallel — reads and writes fan out to all of them.

Honcho  (peer-based persistent user modeling)
  Tracks who you are across sessions. Get a key at honcho.dev
  Enable Honcho? [y/N]: y
    API key: ............
    Workspace [hermes]:

Mem0  (fact extraction via LLM + semantic retrieval)
  Automatically pulls facts from conversations. Get a key at mem0.ai
  Enable Mem0? [y/N]: y
    API key: ............
    User ID [hermes-user]:

Supermemory  (3-layer retrieval: profile + entity graph + document RAG)
  Get a key at console.supermemory.ai
  Enable Supermemory? [y/N]: n

Config written to ~/.hermes/config.yaml
Active providers: honcho, mem0

memory.provider set to comemo. Restart Hermes to activate.
```

---

## Commands

All commands are available via `hermes-comemo <cmd>` after `pip install hermes-comemo`.

### setup

Runs the setup wizard. Prompts for which providers to enable, asks for API keys, and writes the config to `~/.hermes/config.yaml`. Automatically detects existing native Hermes provider configs and pre-fills credentials if found.

### status

Shows what is configured without making any network calls.

```
comemo  (/home/user/.hermes/config.yaml)

  honcho       enabled   workspace: hermes
  mem0         enabled   user_id: hermes-user
  supermemory  disabled
```

### test

Connects to each enabled provider and does a real write and read. Confirms the providers are reachable and working, not just configured.

```
testing Comemo providers  (session: comemo-test-session-a1b2c3)

  honcho       OK     write + recall  (found: TestUser, cross-session)
  mem0         OK     write + recall  (found: TestUser, comemo)
  supermemory  SKIP   not enabled or unavailable
```

### inspect

Queries all enabled providers and shows what is stored. Uses a broad recall by default so you get recent memories without needing to know what to search for.

```
hermes-comemo inspect

inspecting Comemo providers  (query: (all memories), limit: 20)

  honcho  (3 entries)
    [1] User: my name is Anda, i'm building a Hermes plugin
    [2] Assistant: Got it, I'll remember that...
    [3] User: use Honcho for identity tracking

  mem0  (2 entries)
    [1] Anda is building a Hermes plugin for the Nous Research hackathon
    [2] Prefers cloud plus local hybrid memory setups

  supermemory  SKIP   not enabled or unavailable
```

Use `--query` to filter by topic and `--limit` to control how many entries are shown per provider (default 20):

```bash
hermes-comemo inspect --query "python preferences" --limit 5
```

### help

Prints all available commands.

```bash
hermes-comemo help
```

---

## Verifying it works end to end

1. Run `hermes-comemo test` (pip install) — all enabled providers should show OK.
2. Start a Hermes session and have a short conversation. Mention something specific.
3. Run `hermes-comemo inspect` (pip install) — you should see the conversation stored across your enabled providers.
4. Start a new Hermes session and ask "what do you remember about me?" — Comemo injects the recalled memories into the system prompt, so Hermes will reference what was said before.

`hermes-comemo` commands require `pip install hermes-comemo`. Marketplace-only users can verify via `hermes memory status` and by checking that recalled context appears in Hermes sessions.

---

## Providers

### Honcho

Cloud memory that understands who you are over time, not just what was said. Tracks identity and context across sessions using a workspace-scoped store.

Requires an API key from [honcho.dev](https://honcho.dev). Set via `HONCHO_API_KEY`.

### Mem0

Reads every conversation and automatically extracts facts like preferences, context, and recurring topics. Retrieves the most relevant ones at the start of each turn.

Requires an API key from [mem0.ai](https://mem0.ai). Set via `MEM0_API_KEY`.

### Supermemory

Structured knowledge storage with 3-layer retrieval: user profile, entity graph, and document RAG. Memories are scoped to a namespace.

Requires an API key from [supermemory.ai](https://supermemory.ai). Set via `SUPERMEMORY_API_KEY`.

---

## Combinations

You can enable any subset of providers:

| Setup | What you get |
|-------|--------------|
| Honcho only | Cloud identity tracking across devices and sessions. |
| Mem0 only | Automatic fact extraction and semantic recall. |
| Honcho + Mem0 | Identity tracking plus auto-extracted facts. |
| Supermemory only | Structured knowledge store with namespace scoping. |
| All three | Full composite memory across every available backend. |

When Comemo is active it replaces the Hermes built-in memory provider. Existing built-in memories are not migrated automatically.

---

## Manual config

If you prefer to configure without the wizard, add this to `~/.hermes/config.yaml`:

```yaml
memory:
  provider: comemo

plugins:
  comemo:
    honcho:
      enabled: true
      workspace: hermes
    mem0:
      enabled: true
      user_id: hermes-user
    supermemory:
      enabled: false
      namespace: hermes
```

API keys go in `~/.hermes/.env`, not `config.yaml`:

```bash
HONCHO_API_KEY=hc_your_key
MEM0_API_KEY=m0_your_key
SUPERMEMORY_API_KEY=sm_your_key
```

API keys can also be set as environment variables. Comemo reads `HONCHO_API_KEY`, `MEM0_API_KEY`, and `SUPERMEMORY_API_KEY` automatically so you never have to put secrets in a config file.

---

## Failure handling

If a provider goes down, Comemo keeps running on the remaining ones. Failed writes go into a local SQLite retry queue. At the start of the next session, Comemo replays them automatically. Each item is retried up to 5 times.

