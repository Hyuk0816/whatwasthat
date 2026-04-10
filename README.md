# WWT — One Brain for All Your AI Agents

> **Your agents share one brain. Stop re-explaining and writing so many .md files.**

[![PyPI version](https://badge.fury.io/py/whatwasthat.svg)](https://pypi.org/project/whatwasthat/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Supported:** Claude Code · Gemini CLI · Codex CLI
**[한국어 README](README.ko.md)**

---

## What it does

Three coding agents. Three log formats. Three sets of memory that vanish at session end.
WWT collapses them into **one searchable brain** every agent can read from.

```
Claude Code ─┐
Gemini CLI  ─┼──→  one local index  ──→  any agent can recall
Codex CLI   ─┘
```

No more re-explaining context. No more `CLAUDE.md` graveyards. No more *"wait, why did I choose Postgres again?"*

## Quick Start

```bash
pip install whatwasthat              # or: uv tool install whatwasthat
wwt setup                            # DB + hooks + MCP for every installed agent
```

That's it. Existing logs are auto-ingested. Future sessions auto-capture on session end.

## How it works

When a session ends, the agent's hook fires. WWT parses the log, extracts code, chunks the conversation, embeds the search text locally (no API), stores the search index in ChromaDB, and preserves full raw spans in SQLite.

When you ask *"how did I do X last time?"* — any agent calls `search_memory` over MCP, gets a compact preview, and can expand the exact chunk with `recall_chunk`. Including the *why*, not just the *what*.

```
session ends → hook → parse → chunk → embed → ChromaDB + raw SQLite
question     → MCP  → search → score → preview → optional full recall
```

## Upgrading to v1.0.12

v1.0.12 changes the storage shape to preserve full raw conversations and code snippets. Reingest once after upgrading:

```bash
wwt reset --force
wwt setup
```

## Why one brain matters

| Without WWT | With WWT |
|---|---|
| Each agent forgets after every session | Permanent memory across all agents |
| You re-explain context every session | Agent recalls the *why* automatically |
| `.md` files pile up unread | Conversations themselves are the source of truth |
| Claude can't see what Gemini did yesterday | Any agent reads any other's history |

## Search modes

| MCP tool | When the agent calls it |
|---|---|
| `search_memory` | "How did I configure Redis last time?" |
| `search_decision` | "Why Redis instead of Memcached?" |
| `search_all` | Cross-project, cross-agent recall |
| `recall_chunk` | Expand a search result's `chunk_id` into full raw text and code snippets |

`search_memory` **auto-routes** — if your project filter returns nothing useful, it expands to all projects automatically (Self-ROUTE, EMNLP 2024). One call, no retries.

## Three ways to recall

**1. Cross-platform** — *Claude reads what Codex did yesterday*
```
You (in Claude Code):  "How did I set up the JWT refresh token last night?"
WWT:                   Found in [codex-cli] backend-api @ 2026-04-07 23:40
                       → Claude reads the original Codex conversation and answers.
```

**2. Cross-project** — *Reuse a fix from another project*
```
You (in project frontend):  "How did I solve that mTLS cert chain in another project?"
WWT:                        Found in [claude-code] infra-gateway (main) @ 2026-03-22
                            → Same fix, different repo. Recalled in seconds.
```

**3. Both at once** — *Cross-platform AND cross-project*
```
You (in project ml-pipeline, Gemini CLI):  "Why did we drop Kafka for NATS last month?"
WWT search_decision:                       Found in [claude-code] data-platform @ 2026-03-15
                                           → Decision made by Claude in another project,
                                             now answerable from Gemini in this project.
```

## Memory that strengthens itself

Inspired by human spaced repetition: chunks you retrieve often decay slower. Decisions you actually re-use stay sharp; one-off chats fade.

On top of that, scoring is 3-axis (Generative Agents, Stanford 2023):

```
final = relevance × (recency + importance)
```

Old critical decisions beat recent chatter. Because that's how memory should work.

## Install

```bash
pip install whatwasthat              # pip
uv tool install whatwasthat          # uv (recommended)
```

Then run `wwt setup` once. It registers the MCP server and installs the auto-capture hook for every agent already on your machine — Claude Code, Gemini CLI, Codex CLI. Re-runnable, idempotent.

## Requirements

- **Python** 3.10+
- **OS** macOS, Linux (Windows untested)
- **Disk** ~200MB install + ~470MB embedding model
- **Network** 100% local after model download. No API keys. No telemetry.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design, search engine internals
- [CLI_REFERENCE.md](CLI_REFERENCE.md) — every CLI command and flag
- [MCP_REFERENCE.md](MCP_REFERENCE.md) — MCP tool signatures and examples

## Contributing

```bash
uv run pytest tests/ -v
uv run ruff check src/
```

## License

[Apache License 2.0](LICENSE)
