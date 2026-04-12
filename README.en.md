# WWT — One Brain for All Your AI Agents

> **Your agents share one brain. Stop re-explaining and writing so many .md files.**

[![PyPI version](https://badge.fury.io/py/whatwasthat.svg)](https://pypi.org/project/whatwasthat/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Supported:** Claude Code · Gemini CLI · Codex CLI
**[한국어 README](README.md)**

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

When a session ends, the agent's hook fires. WWT parses the log, extracts code, splits the conversation at **three sizes at the same time**, embeds the search text locally (no API), stores the search index in ChromaDB, and keeps the full raw text in SQLite.

When you ask *"how did I do X last time?"* — any agent calls `search_memory` over MCP. WWT searches, **re-sorts the results to match the intent of the question**, returns a compact preview, and lets the agent expand the exact piece with `recall_chunk`. Including the *why*, not just the *what*.

```
session ends → hook → parse → split (3 sizes) → embed → ChromaDB + raw SQLite
question     → MCP  → search → re-sort → preview → optional full recall
```

### Three sizes at once (v1.1)

The same conversation is indexed at **three different sizes** in parallel, so the right-sized context rises naturally.

| Size | Range | Best for |
|---|---|---|
| Short piece | 2 turns | Fact recall — "what was the error again?" |
| Medium piece | 2–6 turns (sliding) | Decision context — "why did we pick X?" |
| Session summary | whole conversation (truncated per turn) | Overview — "what did we do that day?" |

### A second pass over the results (v1.1)

First pass: semantic similarity + keyword match. Second pass: re-sort by how well each candidate fits the intent of the question (no extra AI call):

- **Right size comes first** — decision questions favor medium pieces, code questions favor short pieces, overview questions favor session summaries.
- **Exact word overlap** gets a small bonus.
- **Near-duplicate results** (same session, heavily overlapping turns) get a small penalty.

## Upgrading to v1.1

v1.1 adds the three-size indexing and the second-pass result re-sort. The storage shape changed, so reingest once after upgrading:

```bash
wwt reset --force
wwt setup
```

> Coming from v1.0.x? The same reset also picks up the v1.0.12 raw-text storage shape.

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

## The memory you use most stays sharpest

Like study notes you pull out many times, WWT forgets the pieces you **actually re-open** (`recall_chunk`) more slowly. Flipping through previews doesn't count — if every glance counted as review, noise would pile up.

The search path is fully read-only, so multiple agents can hit the same DB at the same time without stepping on each other.

The final score combines three signals:

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
