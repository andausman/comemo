# Comemo

Comemo is a composite memory provider for Hermes Agent. It runs multiple memory providers at the same time instead of one.

Hermes lets you pick one memory provider. You can use Honcho, Mem0, Supermemory, or Hindsight, but only one at a time. Comemo sits in that single slot and writes to all of them at once. Reads come back merged and deduplicated. If one provider fails, the others keep running.

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
       +---> Hindsight    (optional, cloud)
```

On every write, Comemo fans out to all active providers in parallel using a thread pool. If a provider fails, the write goes into a local SQLite retry queue and replays at the next session start.

On every read, Comemo queries all active providers in parallel, merges the results, and deduplicates identical lines before returning to Hermes.

---

## Install

There are two install paths. Use the one that matches how you got Hermes.

---

### From the Hermes marketplace

```bash
hermes plugins install comemo
```

Then run `hermes memory setup` — Hermes walks through enabling each provider and stores API keys securely in its secret scope. Restart Hermes after and Comemo is live.

---

### From source (GitHub)

```bash
hermes plugins install andausman/comemo
hermes memory setup
```

---

## Setup

**After install:** run `hermes memory setup` — Hermes presents each field from the config schema, writes non-secret settings to `~/.hermes/config.yaml`, and stores API keys securely in its secret scope.

### hermes comemo setup

```
Comemo — Composite Memory Meta-Provider
==========================================

Comemo multiplexes multiple Hermes memory providers simultaneously.
Each provider you enable runs in parallel — reads and writes fan out to all of them.

Honcho  (peer-based persistent user modeling)
  Tracks who you are across sessions. Get a key at honcho.dev
  Enable Honcho? [y/N]: y
  Workspace [hermes]:

Mem0  (fact extraction via LLM + semantic retrieval)
  Automatically pulls facts from conversations. Get a key at mem0.ai
  Enable Mem0? [y/N]: y
  User ID [hermes-user]:

Supermemory  (3-layer retrieval: profile + entity graph + document RAG)
  Get a key at console.supermemory.ai
  Enable Supermemory? [y/N]: n

Config written to ~/.hermes/config.yaml
Active providers: honcho, mem0

Run 'hermes memory setup' to set your API keys, then start a new session.
```

---

## Commands

Run these commands from your terminal once Comemo is installed and active.

### setup

Runs the setup wizard. Prompts for which providers to enable and writes non-secret settings to `~/.hermes/config.yaml`. Run `hermes memory setup` separately to set API keys.

### status

Shows what is configured without making any network calls.

```
comemo  (/home/user/.hermes/config.yaml)

  honcho       enabled   workspace=hermes
  mem0         enabled   user_id=hermes-user
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
hermes comemo inspect

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
hermes comemo inspect --query "python preferences" --limit 5
```

---

## Verifying it works end to end

1. Run `hermes comemo test` — all enabled providers should show OK.
2. Start a Hermes session and have a short conversation. Mention something specific.
3. Run `hermes comemo inspect` — you should see the conversation stored across your enabled providers.
4. Start a new Hermes session and ask "what do you remember about me?" — Comemo injects the recalled memories into the system prompt, so Hermes will reference what was said before.

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

### Hindsight

Vectorized knowledge graph with entity resolution. Stores memories as interconnected entities and uses hybrid (vector + graph) retrieval for precise recall.

Requires an API key from [hindsight.vectorize.io](https://hindsight.vectorize.io). Set via `HINDSIGHT_API_KEY`. Optionally set a `bank_id` to scope memories per project or profile.

---

## Combinations

You can enable any subset of providers:

| Setup | What you get |
|-------|--------------|
| Honcho only | Cloud identity tracking across devices and sessions. |
| Mem0 only | Automatic fact extraction and semantic recall. |
| Honcho + Mem0 | Identity tracking plus auto-extracted facts. |
| Supermemory only | Structured knowledge store with namespace scoping. |
| Hindsight only | Knowledge graph with entity resolution and hybrid retrieval. |
| All four | Full composite memory across every available backend. |

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

API keys are stored securely by Hermes via `hermes memory setup` — never written to `config.yaml`. Comemo reads them through the Hermes secret scope (`HONCHO_API_KEY`, `MEM0_API_KEY`, `SUPERMEMORY_API_KEY`).

---

## Failure handling

If a provider goes down, Comemo keeps running on the remaining ones. Failed writes go into a local SQLite retry queue. At the start of the next session, Comemo replays them automatically. Each item is retried up to 5 times.
