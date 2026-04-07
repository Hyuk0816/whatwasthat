# WWT (whatwasthat)

> **Decision Memory for AI Coding Agents** — Remember why you coded it that way.

[![PyPI version](https://badge.fury.io/py/whatwasthat.svg)](https://pypi.org/project/whatwasthat/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Supported Agents:** Claude Code | Gemini CLI | Codex CLI
**[한국어 README](README.ko.md)**

---

## The Problem

You pair-programmed with an AI agent for hours. You made architecture decisions, debugged a tricky race condition, chose Redis over Memcached for specific reasons. Next session — the AI starts from zero, and so does your memory of *why*.

- "How did I configure the Redis cache last time?"
- "Why did we choose PostgreSQL over MongoDB?"
- "How did I fix that mTLS certificate issue in another project?"

You tried dumping notes into `CLAUDE.md`. They pile up. You never look at them again.

## The Solution

WWT auto-captures every AI coding conversation, indexes it semantically, and lets you search across **all agents, all projects** with one command.

```
Session ends → Auto-capture → Parse → Chunk → Embed → Searchable
```

No workflow changes. No manual logging. It just works.

## Quick Start

```bash
# Install
pip install whatwasthat          # or: uv tool install whatwasthat

# One-command setup: DB + hooks + MCP for all installed agents
wwt setup

# Search your past conversations
wwt search "Redis cache configuration"

# Find decision context — why did you make that choice?
wwt why "Why did we choose PostgreSQL?"
```

> `wwt setup` initializes the database, installs auto-capture hooks, and registers the MCP server for every installed agent. First run downloads the embedding model (~470MB). Safe to re-run.

---

## Key Features

### `wwt why` — Decision Memory Search

The feature that defines WWT. When you ask "why did we do it that way?", WWT boosts results containing decision patterns — *"chose X because"*, *"instead of Y"*, *"trade-off between"*.

```bash
wwt why "Why Redis instead of Memcached?"
# → Finds the conversation where you discussed persistence, LRU eviction,
#   and decided Redis was the better fit.
```

### Code-Aware Search

Code snippets are extracted and preserved from conversations. Search specifically for code:

```bash
wwt search "Dockerfile" --mode code
# → Returns only conversations that contain code blocks
```

### Cross-Agent, Cross-Project Memory

All conversations from Claude Code, Gemini CLI, and Codex CLI are unified in one searchable index. An insight from a Claude session is findable from Gemini.

```bash
wwt search "Docker multi-stage build" --all    # Search across all projects
wwt search "JWT auth" --source gemini-cli       # Filter by platform
wwt search "deploy config" --branch feature/ci  # Filter by git branch
```

### Hybrid Search Engine

Vector similarity (60%) + BM25 keyword matching (40%). Semantic understanding catches paraphrases; keyword matching catches exact terms. Korean morpheme analysis via kiwipiepy.

### Fully Local & Private

Your data never leaves your machine. No cloud APIs, no telemetry, no analytics. Only exception: initial embedding model download from HuggingFace.

### Lightweight Install

ONNX Runtime replaces PyTorch — no more 1.4GB dependency tree. Total install: ~200MB + embedding model.

---

## Usage

### CLI

| Command | Description |
|---------|-------------|
| `wwt setup` | Initialize DB + hooks + MCP for all platforms |
| `wwt search <query>` | Semantic search across conversations |
| `wwt why <query>` | Decision-context search (pattern boosting) |
| `wwt search <query> --mode code` | Search only code-containing conversations |
| `wwt ingest <path>` | Manually ingest a log file or directory |
| `wwt reset` | Delete all indexed data |

**Filters** (apply to `search` and `why`):

```bash
--project, -p    # Filter by project name (fuzzy match)
--source, -s     # Platform: claude-code, gemini-cli, codex-cli
--branch, -b     # Git branch filter
--all, -a        # Search all projects (skip project filter)
--mode, -m       # Search mode: decision, code
```

### MCP (Natural Language)

After `wwt setup`, LLMs call these tools automatically when you mention past conversations:

| Tool | Purpose |
|------|---------|
| `search_memory` | Project-aware search with filters |
| `search_all` | Cross-project, cross-platform search |
| `search_decision` | Decision-context search ("Why did we choose X?") |
| `ingest_session` | Ingest conversation logs |

```
You: "How did I set up the Redis cache last time?"
AI:  [calls search_memory] → Returns 3 relevant conversations with context
```

### Auto-Capture

`wwt setup` installs hooks for each platform — conversations are captured automatically:

| Platform | Hook Type | Trigger |
|----------|-----------|---------|
| Claude Code | Stop Hook | Session end |
| Gemini CLI | AfterAgent Hook | Agent completion |
| Codex CLI | Stop Hook | Session end |

---

## How It Works

```
┌─────────────┐  ┌──────────────┐  ┌─────────────┐
│ Claude Code  │  │  Gemini CLI  │  │  Codex CLI  │
│   (JSONL)    │  │ (JSON/JSONL) │  │   (JSONL)   │
└──────┬───────┘  └──────┬───────┘  └──────┬──────┘
       └─────────────────┼─────────────────┘
                         ▼
              ┌──────────────────┐
              │  Auto-Detect     │  SessionParser Protocol
              │  Parser          │  (3 format parsers)
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │  Extract Code    │  Preserve code snippets
              │  Clean Content   │  Remove noise/tags
              │  Chunk (2-6 turns│  Sliding window, 2-turn overlap
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │  ONNX Embedding  │  multilingual-e5-small (384d)
              │  (CPU, no torch) │  100+ languages supported
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │  ChromaDB        │  HNSW index (cosine)
              │  + BM25 index    │  kiwipiepy Korean tokenizer
              │  ~/.wwt/data/    │
              └──────────────────┘
```

For detailed architecture, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Comparison

| Capability | **WWT** | Manual Notes | grep Logs | mem0 |
|---|:---:|:---:|:---:|:---:|
| Auto-capture | Yes | No | No | No |
| Semantic search | Yes | No | No | Yes |
| Decision search (`why`) | Yes | No | No | No |
| Code snippet search | Yes | No | Partial | No |
| Cross-project | Yes | Manual | Painful | Yes |
| Cross-agent | Yes | N/A | Per-agent | No |
| Fully local | Yes | Yes | Yes | No |
| Setup effort | 1 command | Ongoing | Scripts | API key |

---

## Requirements

- **Python**: 3.10+
- **OS**: macOS, Linux (Windows untested)
- **Disk**: ~1GB (dependencies + embedding model)
- **RAM**: ~2GB (during search)

## Data Storage

```
~/.wwt/data/vector/          # ChromaDB vector index
~/.wwt/ingest.log            # Auto-capture log
~/.cache/huggingface/hub/    # Embedding model cache (~470MB)
```

---

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — System design, data flow, search engine internals
- [CLI_REFERENCE.md](CLI_REFERENCE.md) — Complete CLI command reference
- [MCP_REFERENCE.md](MCP_REFERENCE.md) — MCP tool signatures and examples

## Contributing

Contributions welcome! WWT uses `pytest` for testing and `ruff` for linting:

```bash
uv run pytest tests/ -v
uv run ruff check src/
```

## License

[Apache License 2.0](LICENSE)
