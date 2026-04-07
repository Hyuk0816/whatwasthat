# WWT CLI Reference

## Installation

### System Requirements

- **Python**: 3.10+
- **OS**: macOS, Linux (Windows untested)
- **Disk**: ~1.4GB (dependencies + embedding model)
- **RAM**: ~2GB (search runtime)

### Install via pip

```bash
pip install whatwasthat
```

### Install via uv (recommended)

```bash
uv tool install whatwasthat
```

### Verify Installation

```bash
wwt --help
```

Output:
```
 Usage: wwt [OPTIONS] COMMAND [ARGS]...

 whatwasthat - AI 대화 기억 검색

╭─ Commands ─────────────────────────────────────────────────────────╮
│ init       WWT 초기 설정 (DB 디렉토리 생성).                        │
│ ingest     대화 로그를 벡터 DB로 적재.                              │
│ reset      모든 적재 데이터 삭제 (벡터 DB 초기화).                  │
│ search     과거 대화에서 관련 기억 검색.                             │
│ setup      WWT 전체 설정 — DB 초기화 + Stop Hook + MCP 등록.       │
│ why        의사결정 맥락 검색 — '왜 그렇게 했지?' 에 답합니다.      │
╰────────────────────────────────────────────────────────────────────╯
```

## Command Reference

### wwt setup

Initialize WWT with database, hooks, and MCP registration.

**Syntax**
```bash
wwt setup
```

**What it does**

1. Creates ChromaDB vector index (`~/.wwt/data/vector/`)
2. Installs Stop Hook script (`~/.claude/hooks/wwt_auto_ingest.sh`)
3. Registers Stop Hook in `~/.claude/settings.json`
4. Registers MCP server globally (if Claude CLI is installed)
5. Registers Gemini CLI MCP and AfterAgent hook (if Gemini is installed)
6. Registers Codex CLI MCP and Stop Hook (if Codex is installed)
7. Auto-ingests existing session logs from all platforms

**Output Example**
```
DB 초기화 중... (최초 실행 시 임베딩 모델 ~470MB 다운로드)
✓ DB 초기화 완료
✓ Stop Hook 스크립트 설치 완료
✓ Stop Hook 등록 완료 (settings.json)
✓ MCP 서버 글로벌 등록 완료
✓ Gemini CLI MCP 서버 등록 완료
✓ Codex CLI MCP 서버 등록 완료

[Claude Code] 120개 세션 적재 중...
  [Claude Code] 50% (60/120) — 45 세션, 1200 청크
  [Claude Code] 100% (120/120) — 95 세션, 2340 청크
✓ [Claude Code] 완료: 95 세션, 2340 청크 (340 신규 임베딩)

설정 완료! 각 플랫폼을 재시작하여 확인하세요.
```

**Notes**

- Safe to run multiple times (idempotent)
- Requires internet on first run (HuggingFace model download ~470MB)
- ~2-3 minutes on first run (includes model download)

---

### wwt init

Initialize database only (skip hooks and MCP).

**Syntax**
```bash
wwt init
```

**What it does**

1. Creates `~/.wwt/data/vector/` directory
2. Initializes empty ChromaDB collection

**Output Example**
```
WWT 초기화 완료: /Users/user/.wwt
```

**Use Case**

When you only want the database without auto-ingest or MCP.

---

### wwt ingest

Ingest conversation logs into the vector database.

**Syntax**
```bash
wwt ingest <path> [OPTIONS]
```

**Arguments**

| Argument | Type | Description |
|----------|------|-------------|
| `<path>` | Path | JSONL/JSON file or directory (recursive glob) |

**Supported Formats**

- Claude Code: `*.jsonl`
- Gemini CLI: `*.json` (with `messages` array) or `*.jsonl`
- Codex CLI: `*.jsonl` (with `session_meta`)
- Auto-detected: Parser detects format from file content

**Behavior**

- **Single file**: Ingest that session
- **Directory**: Recursively ingest all `.jsonl` and `.json` files
- **Idempotent**: Duplicate chunks detected by ID, skipped during embedding
- **Incremental**: Only changed chunks are re-embedded

**Examples**

Ingest single Claude Code session:
```bash
wwt ingest ~/.claude/projects/my-project/sessions/session-abc123.jsonl
```

Ingest all Claude Code projects:
```bash
wwt ingest ~/.claude/projects/
```

Ingest from current directory:
```bash
wwt ingest ./exported-sessions/
```

**Output Example**
```
  파싱: 10/50 세션, 240 청크
  파싱: 50/50 세션, 1200 청크

완료: 48 세션, 1200 청크 (240 신규 임베딩)
```

**Performance**

- ~50ms per chunk embedding (CPU)
- Bulk ingest defers BM25 rebuild until end
- 1000 chunks: ~1 minute

---

### wwt search

Search across all conversations (hybrid vector + BM25).

**Syntax**
```bash
wwt search <query> [OPTIONS]
```

**Arguments**

| Argument | Type | Description |
|----------|------|-------------|
| `<query>` | String | Natural language search query |

**Options**

| Option | Short | Type | Description |
|--------|-------|------|-------------|
| `--project <name>` | `-p` | String | Filter by project name (fuzzy match supported) |
| `--all` | `-a` | Flag | Search across all projects (ignores `--project`) |
| `--source <platform>` | `-s` | String | Filter by platform: `claude-code`, `gemini-cli`, `codex-cli` |
| `--branch <name>` | `-b` | String | Filter by git branch (e.g., `main`, `feature/auth`) |
| `--mode <mode>` | `-m` | String | Search mode: `decision`, `code` (default: hybrid) |

**Search Modes**

| Mode | Behavior |
|------|----------|
| (default) | Hybrid: 60% vector + 40% BM25 |
| `decision` | Boost chunks with decision patterns (1.3×): "대신", "선택", "결정", "이유" |
| `code` | Filter: only chunks with code snippets |

**Examples**

Basic search in current project:
```bash
wwt search "Redis 캐시 설정 어떻게 했지?"
```

Search in specific project:
```bash
wwt search "Docker multi-stage build" --project backend-api
```

Search across all projects:
```bash
wwt search "JWT 인증 구현" --all
```

Search by platform:
```bash
wwt search "PostgreSQL 인덱스" --source claude-code
```

Search by branch:
```bash
wwt search "마이그레이션" --branch main
```

Search for decision context:
```bash
wwt search "왜 MongoDB 대신 PostgreSQL" --mode decision
```

Search for code examples:
```bash
wwt search "FastAPI" --mode code
```

Combine filters (AND logic):
```bash
wwt search "캐싱" --project backend --branch feature/cache --source gemini-cli
```

**Output Format**

```
3개 세션에서 관련 기억을 찾았습니다:

  1. backend-api (main) [claude-code] (점수: 0.93)
     [user]: Redis 캐시 설정해줄 수 있어?
     [assistant]: TTL을 300초로 설정하고 invalidation은 이벤트 기반으로...

  2. backend-api (feature/cache) [codex-cli] (점수: 0.87)
     [user]: 캐시 무효화 정책 어떻게 할까?
     [assistant]: pub/sub 패턴을 사용하면 좋습니다...

  3. infra (main) [gemini-cli] (점수: 0.79)
     [user]: 캐시 레이어 최적화
     [assistant]: Redis Cluster를 사용하면...
```

**Project Name Fuzzy Matching**

Project names are matched fuzzily:
- Case-insensitive: `MyProject` ≈ `myproject`
- Normalized: `my-project` ≈ `my_project`
- Substring: `backend` matches `backend-api`

**Minimum Score Filter**

Results with score < 0.5 are excluded (no semantic relevance).

---

### wwt why

Search for decision context (specialized mode of `search`).

**Syntax**
```bash
wwt why <query> [OPTIONS]
```

**Arguments**

| Argument | Type | Description |
|----------|------|-------------|
| `<query>` | String | Decision-related query (e.g., "왜 Redis를 선택했지?") |

**Options**

Same as `search`:
- `--project <name>` / `-p`
- `--all` / `-a`
- `--source <platform>` / `-s`
- `--branch <name>` / `-b`

**Behavior**

Equivalent to `wwt search <query> --mode decision`

Boosts chunks matching decision patterns:
- Korean: "대신", "선택", "결정", "이유", "비교", "으로 갔", "하기로", "보다", "때문에", "장단점"
- English: "instead of", "chose", "decided", "because", "compared", "trade-off", "prefer", "rather than"

**Examples**

```bash
wwt why "왜 MongoDB 대신 PostgreSQL을 선택했지?"
```

```bash
wwt why "왜 Docker 이미지가 커졌지?" --project backend-api
```

```bash
wwt why "캐시 구현을 바꾼 이유" --all
```

**Output**

Same format as `search`, but results prioritize decision-related content.

---

### wwt reset

Delete all ingested data (irreversible).

**Syntax**
```bash
wwt reset [OPTIONS]
```

**Options**

| Option | Type | Description |
|--------|------|-------------|
| `--force` / `-f` | Flag | Skip confirmation, delete immediately |

**Default Behavior**

Prompts for confirmation:
```
모든 적재 데이터를 삭제합니다. 계속할까요? [y/N]:
```

**With --force**

```bash
wwt reset --force
```

Skips prompt, deletes immediately.

**Output**

```
✓ 모든 적재 데이터 삭제 완료
  다시 적재하려면: wwt setup 또는 wwt ingest <경로>
```

**Recovery**

Data is permanently deleted from `~/.wwt/data/vector/`. Re-run `wwt setup` or `wwt ingest` to repopulate.

---

## Data Directories

### WWT Home

```
~/.wwt/
├── data/
│   └── vector/                    # ChromaDB index
│       ├── chroma.sqlite3         # Vector metadata
│       ├── 2da2e4d6.parquet       # Vector embeddings (HNSW index)
│       └── 2da2e4d6.parquet.pkl   # Metadata
└── ingest.log                      # Auto-ingest log (from hooks)
```

### HuggingFace Model Cache

```
~/.cache/huggingface/hub/
└── models--intfloat--multilingual-e5-small/
    ├── snapshots/
    │   └── [hash]/
    │       ├── onnx/model.onnx     # ONNX weights (~380MB)
    │       ├── tokenizer.json
    │       └── tokenizer_config.json
    └── refs/
        └── main                     # Pointer to latest
```

First run downloads ~470MB; subsequent runs use cache.

---

## Hook Integration

Once `wwt setup` completes, conversation logs are automatically ingested.

### Claude Code (Stop Hook)

Hook runs when session stops:

```
~/.claude/settings.json:
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "bash ~/.claude/hooks/wwt_auto_ingest.sh",
        "timeout": 15,
        "async": true
      }]
    }]
  }
}
```

Log: `~/.wwt/ingest.log`

### Gemini CLI (AfterAgent Hook)

Hook runs after agent completes:

```
~/.gemini/settings.json:
{
  "hooks": {
    "AfterAgent": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "bash ~/.wwt/hooks/gemini_ingest.sh",
        "name": "wwt-ingest",
        "timeout": 60000
      }]
    }]
  }
}
```

### Codex CLI (Stop Hook)

Hook runs when session stops:

```
~/.codex/hooks.json:
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "bash ~/.wwt/hooks/codex_ingest.sh"
      }]
    }]
  }
}
```

---

## Performance Tips

### For Large Datasets

1. Ingest in batches:
   ```bash
   wwt ingest ~/projects/project-a/
   wwt ingest ~/projects/project-b/
   ```

2. Let bulk ingest finish before searching (BM25 rebuild):
   ```bash
   wwt ingest ~/projects/  # Defers BM25 rebuild
   # Wait 10-30 seconds for rebuild
   wwt search "query"
   ```

### For Frequent Searches

Embedded models are cached after first load. Subsequent searches are fast.

### For Memory Constraints

- BM25 index is rebuilt only when chunks change
- Vector index uses HNSW (efficient memory usage)
- No cloud APIs (purely local)

---

## Troubleshooting

### Embedding Model Download Stuck

If `wwt setup` hangs on "모델 다운로드 중...":

```bash
# Check HuggingFace hub connectivity
ping huggingface.co

# Manually download model:
python -c "from huggingface_hub import snapshot_download; snapshot_download('intfloat/multilingual-e5-small')"

# Retry setup
wwt setup
```

### No Results Found

1. Check database is initialized:
   ```bash
   ls -la ~/.wwt/data/vector/
   ```

2. Verify data was ingested:
   ```bash
   wwt ingest ~/path/to/logs
   ```

3. Try broader query or `--all` flag:
   ```bash
   wwt search "your query" --all
   ```

### Hook Not Running

1. Verify Stop Hook is registered:
   ```bash
   cat ~/.claude/settings.json | grep wwt
   ```

2. Re-run setup:
   ```bash
   wwt setup
   ```

3. Restart Claude Code or Gemini CLI

4. Check log:
   ```bash
   tail -f ~/.wwt/ingest.log
   ```

### MCP Not Showing Up

1. Check MCP is registered:
   ```bash
   claude mcp list
   # or
   gemini mcp list
   ```

2. Re-register if missing:
   ```bash
   wwt setup
   ```

3. Restart Claude Code / Gemini CLI

### Permission Denied

If you get "Permission denied" errors:

```bash
# Fix hook permissions
chmod +x ~/.claude/hooks/wwt_auto_ingest.sh
chmod +x ~/.wwt/hooks/*.sh

# Retry ingest
wwt ingest ~/path/to/logs
```

