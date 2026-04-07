# WWT Architecture Documentation

## System Overview

WWT (What Was That?) is a semantic search engine for AI conversation logs. It automatically parses, chunks, embeds, and indexes conversation histories from Claude Code, Gemini CLI, and Codex CLI.

```
┌────────────────────────────────────────────────────────────┐
│                    User Interfaces                         │
├────────────┬──────────────────────────┬───────────────────┤
│ CLI (typer) │  MCP Server (FastMCP)   │  Auto-Ingest Hook │
│  - search  │  - search_memory        │  - Stop Hook      │
│  - ingest  │  - search_all           │  - AfterAgent Hook│
│  - why     │  - search_decision      │                   │
│  - setup   │  - ingest_session       │                   │
└────────────┴──────────────────────────┴───────────────────┘
              │                    │                  │
              └────────────────────┼──────────────────┘
                                   │
         ┌─────────────────────────▼────────────────────┐
         │           Pipeline Layer                     │
         ├──────────────────────────────────────────────┤
         │  Parser (Detect 3 formats)                   │
         │  ├─ ClaudeCodeParser (JSONL)                │
         │  ├─ GeminiCliParser (JSON + JSONL)          │
         │  └─ CodexCliParser (JSONL + RolloutItem)    │
         │                                              │
         │  Chunker (Sliding window, 2-6 turns)        │
         │  ├─ Overlap: 2 turns                        │
         │  └─ Min length: 200 chars + 1 user turn     │
         └─────────────────────────┬────────────────────┘
                                   │
         ┌─────────────────────────▼────────────────────┐
         │        Embedding Layer (ONNX)                │
         ├──────────────────────────────────────────────┤
         │  OnnxEmbeddingFunction                       │
         │  ├─ Model: intfloat/multilingual-e5-small   │
         │  ├─ Dim: 384                                │
         │  ├─ Runtime: onnxruntime (CPU)              │
         │  └─ Provider: CPUExecutionProvider           │
         └─────────────────────────┬────────────────────┘
                                   │
         ┌─────────────────────────▼────────────────────┐
         │       Search Engine Layer                    │
         ├──────────────────────────────────────────────┤
         │  Hybrid Search                               │
         │  ├─ Vector: HNSW (60% weight)               │
         │  ├─ BM25: Keyword (40% weight)              │
         │  ├─ Tokenizer: kiwipiepy (Korean morpheme)  │
         │  └─ Session grouping                        │
         │                                              │
         │  Search Modes                                │
         │  ├─ default: Hybrid vector + BM25           │
         │  ├─ decision: Pattern boost (1.3x)          │
         │  └─ code: Code snippet filter               │
         └─────────────────────────┬────────────────────┘
                                   │
         ┌─────────────────────────▼────────────────────┐
         │       Storage Layer                          │
         ├──────────────────────────────────────────────┤
         │  ChromaDB                                    │
         │  ├─ Distance: cosine                        │
         │  ├─ Index: HNSW                             │
         │  └─ Path: ~/.wwt/data/vector/               │
         │                                              │
         │  Metadata per Chunk                          │
         │  ├─ session_id                              │
         │  ├─ project, git_branch                     │
         │  ├─ source (platform)                       │
         │  ├─ timestamp                               │
         │  ├─ has_code, code_languages                │
         │  └─ turn_count                              │
         └──────────────────────────────────────────────┘
```

## Data Flow Pipeline

### 1. Input: Multiple Log Formats

```
Claude Code (~/.claude/projects/)
└─ [session-id].jsonl
   ├─ type: "user" | "assistant"
   ├─ message.role: "user" | "assistant"
   ├─ message.content: str | list[{type: "text", text: str}]
   ├─ sessionId, cwd, gitBranch, timestamp
   └─ Repeat per turn

Gemini CLI (~/.gemini/tmp/)
├─ JSON: [session]/chats/[id].json
│  ├─ sessionId, startTime
│  └─ messages[]: {type: "user"|"gemini", content: str, timestamp}
└─ JSONL: Alternative format with session_metadata

Codex CLI (~/.codex/sessions/)
└─ [session].jsonl
   ├─ type: "session_meta" | "event_msg"
   ├─ payload.type: "user_message" | "agent_message"
   ├─ payload.message, payload.id
   ├─ git.branch, cwd
   └─ Repeat per event
```

### 2. Parsing Phase

**Parser Detection** (`detect_parser(file_path: Path) -> SessionParser | None`)

Tries parsers in order: `[CodexCliParser, GeminiCliParser, ClaudeCodeParser]`

Each parser checks file format markers:
- **CodexCliParser**: `session_meta` + `event_msg` objects
- **GeminiCliParser**: `messages` array OR `session_metadata` + `content` list
- **ClaudeCodeParser**: `sessionId` field OR `type` in ("user", "assistant")

**Content Cleaning** (`_clean_content(text: str, role: str) -> str`)

```
Raw input
  ↓ Remove code blocks (```...```)
  ↓ Remove system blocks (<system-reminder>, etc.)
  ↓ Remove HTML/XML tags
  ↓ Normalize whitespace
  ↓ Truncate assistant responses > 500 chars
  ↓ Cleaned text
```

**Code Extraction** (`_extract_code_blocks(text: str) -> list[dict[str, str]]`)

Extracts `{language, code}` pairs from markdown code blocks.
- Minimum 10 chars per block (skip trivial snippets)
- Language auto-detected or marked as "unknown"

**Turn Filtering** (`_is_meaningful(text: str, role: str) -> bool`)

Skips:
- Text < 5 chars
- Patterns: "[Request interrupted", "확인합니다", "진행하겠습니다"
- Short assistant status messages (< 80 chars) matching `하겠습니다|완료되었습니다|변경 완료`

**SessionMeta Extraction**

From first lines: `sessionId`, `cwd` (project name), `gitBranch`, `timestamp`
- If missing: fallback to file name, empty string, or current time

### 3. Chunking Phase

**Input**: `list[Turn]` + `SessionMeta`

**Sliding Window Chunking**

```
Config:
  min_turns: 2
  max_turns: 6
  overlap: 2 turns
  step: max_turns - overlap = 4

Example (10 turns):
[T0 T1 T2 T3 T4 T5 T6 T7 T8 T9]

Chunk 0: [T0 T1 T2 T3 T4 T5]  ← indices 0:6
Chunk 1: [T4 T5 T6 T7 T8 T9]  ← indices 4:10 (overlap: T4, T5)
```

**Chunk Validation**

Chunk is kept if:
1. Has ≥ 1 user turn
2. Raw text ≥ 200 chars
3. Turns ≥ min_turns

**Chunk ID Generation**

```python
chunk_id = sha256(f"{session_id}:c{start_index}").hexdigest()[:16]
```

Deterministic: Same session + start index = same chunk ID (idempotent upsert).

**Chunk Metadata**

```python
{
  "session_id": str,
  "project": str,            # From cwd basename
  "project_path": str,       # Full cwd
  "git_branch": str,
  "source": str,             # "claude-code" | "gemini-cli" | "codex-cli"
  "timestamp": str,          # ISO format
  "has_code": "true" | "false",
  "code_languages": str,     # Comma-separated
  "chunk_index": int,        # Position in chunks
  "turn_count": int,         # Number of turns in chunk
}
```

### 4. Embedding Phase

**ONNX Runtime (CPU)**

```
Model: intfloat/multilingual-e5-small
  ├─ 118M parameters
  ├─ 384 dimensions
  ├─ 100+ language support (Korean + English)
  └─ ~470MB download (HuggingFace hub, cached)

Tokenizer: HuggingFace tokenizers
  ├─ Max length: 512
  ├─ Padding: enabled
  └─ Truncation: enabled

e5 Convention:
  ├─ Query prefix: "query: {text}"
  ├─ Document prefix: (none, implicit)
  └─ Mean pooling + L2 norm
```

**Process**

```
Input text list
  ↓ Add "query: " prefix (e5 convention)
  ↓ Tokenize (tokenizers library)
  ├─ input_ids: shape (batch, 512)
  ├─ attention_mask: shape (batch, 512)
  └─ token_type_ids: shape (batch, 512)
  ↓ Run ONNX inference
  ↓ Token embeddings: (batch, seq_len, 384)
  ↓ Mean pooling (apply attention mask)
  ↓ L2 normalization
  ↓ Output: (batch, 384)
```

**Cost**

- ~50ms per query on M1 MacBook CPU
- No GPU required
- Lazy loaded: Models cached, first query ≈ 2s (download + load)

### 5. Storage Phase

**ChromaDB Initialization**

```python
client = chromadb.PersistentClient(path="~/.wwt/data/vector/")
collection = client.get_or_create_collection(
    name="wwt_chunks",
    metadata={"hnsw:space": "cosine"},
    embedding_function=OnnxEmbeddingFunction(),
)
```

**Upsert Strategy** (`upsert_session_chunks`)

Incremental upsert to avoid re-embedding unchanged chunks:

```python
1. Fetch existing chunks by session_id
2. Compare new chunks with old:
   - If chunk ID exists AND turn_count same → skip embedding
   - Else → include in batch
3. Delete stale chunks (old IDs not in new batch)
4. Upsert changed chunks only
5. Conditional BM25 rebuild (skip during bulk ingest)
```

**BM25 Index Rebuild**

```
Lazy rebuild after bulk ingest (e.g., wwt setup):
  1. Ingest N files with rebuild_bm25=False
  2. At end: vector.rebuild_index()
  
Per-file ingest (wwt ingest single.jsonl):
  - rebuild_bm25=True (immediate)
```

## Search Phase

### Hybrid Search Algorithm

**Step 1: Vector Search**

```
query_text
  ↓ Add "query: " prefix
  ↓ Embed via ONNX
  ↓ ChromaDB query (cosine distance)
  ↓ candidate_k = min(top_k * 3, collection.count())
  ↓ Results: [(chunk_id, score), ...]
  ↓ Convert distance → similarity: score = max(0, 1 - distance)
```

**Step 2: BM25 Search**

```
query_text
  ↓ Tokenize (kiwipiepy)
    ├─ CamelCase split: SheDataset → She Dataset
    ├─ Extension split: file.vue → file vue
    ├─ Morpheme analysis: 한국어 → 형태소
    └─ Filter: NN*, SL, SN, VV, VA, XR tags, len > 1
  ↓ BM25.get_scores(tokens) → raw scores
  ↓ Normalize: score / max(raw_scores)
  ↓ Top candidate_k by BM25 score
  ↓ Apply filters (project, source, git_branch)
  ↓ Results: [(chunk_id, normalized_score), ...]
```

**Step 3: Hybrid Scoring**

```
For each chunk in (vector ∪ BM25 results):
  vec_score = vec_results.get(chunk_id, 0.0)
  bm25_score = bm25_results.get(chunk_id, 0.0)
  hybrid = vec_score * 0.6 + bm25_score * 0.4

Sort by hybrid, return top top_k
```

### Search Modes

**1. Default Mode**

Hybrid vector + BM25 search, no special filtering.

```python
engine.search(query, mode=None)
```

**2. Decision Mode** (`mode="decision"`)

Boosts chunks matching decision patterns 1.3×:

```python
patterns_ko = r"대신|선택|결정|이유|비교|으로 갔|하기로|보다|때문에|장단점"
patterns_en = r"instead of|chose|decided|because|compared|trade-off|prefer|rather than"

if pattern_match(doc_text):
    score = min(score * 1.3, 1.0)  # Boost and cap at 1.0
```

**3. Code Mode** (`mode="code"`)

Pre-filter: Keep only chunks with `has_code == "true"`

```python
hits = [(cid, score, meta) for cid, score, meta in hits
        if meta.get("has_code") == "true"]
```

### Filtering

**Multi-Filter with $and**

```python
filters = []
if project:
    filters.append({"project": project})
if source:
    filters.append({"source": source})
if git_branch:
    filters.append({"git_branch": git_branch})

# ChromaDB where clause:
if len(filters) > 1:
    where = {"$and": filters}
elif len(filters) == 1:
    where = filters[0]
else:
    where = None
```

### Session Grouping

Results are grouped by session_id and sorted by best chunk score:

```python
session_chunks = defaultdict[session_id] = [(chunk, score), ...]

for session_id, chunk_scores in session_chunks.items():
    best_score = max(chunk_scores)[1]
    chunks = [c for c, _ in chunk_scores]
    summary = chunks[0].raw_text[:200]
    
    SearchResult(
        session_id=session_id,
        chunks=chunks,           # All chunks in session
        summary=summary,
        score=best_score,        # Best chunk's score
        project=chunks[0].project,
        git_branch=chunks[0].git_branch,
        source=chunks[0].source,
    )
```

## Key Components

### Models

**Turn**: Conversation turn
- `role`: "user" | "assistant"
- `content`: Cleaned text
- `timestamp`: Optional datetime
- `source`: Platform identifier
- `code_snippets`: `list[{language: str, code: str}]`

**Chunk**: Topical unit for indexing
- `id`: Deterministic chunk ID (sha256[:16])
- `session_id`: Parent session
- `turns`: Sliding window of Turns
- `raw_text`: Formatted text
- `project`, `project_path`, `git_branch`: Metadata
- `source`: Platform
- `timestamp`: Session start time
- `code_snippets`: Extracted code blocks

**SearchResult**: Query result
- `session_id`: Source session
- `chunks`: Top chunks from session
- `summary`: First 200 chars of best chunk
- `score`: Best chunk's score (0-1)
- `project`, `git_branch`, `source`: Metadata

**SessionMeta**: Session metadata
- `session_id`, `project`, `project_path`, `git_branch`
- `started_at`: datetime
- `turn_count`: int
- `source`: Platform

### Config

```python
WWT_HOME = ~/.wwt
WWT_DATA_DIR = ~/.wwt/data
CHROMA_DB_PATH = ~/.wwt/data/vector
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
```

## Performance Characteristics

| Operation | Time | Cost |
|-----------|------|------|
| First embedding load | ~2s | HuggingFace download (~470MB) |
| Embed 1 chunk (512 tokens) | ~50ms | CPU-bound |
| BM25 index build (10K chunks) | ~2s | Full scan + tokenization |
| Vector query (cosine HNSW) | ~100ms | Index lookup |
| Hybrid search result | ~150-200ms | Parallel vector + BM25 |
| Session grouping | ~5ms | Dictionary merge |

## Scalability

- **Chunks**: Tested with 10K+ chunks
- **Sessions**: Hundreds of sessions (tens of thousands of chunks)
- **Query latency**: <200ms for typical queries
- **Memory**: ~2GB for search runtime (ChromaDB + BM25 index)
- **Disk**: ~500MB per 10K chunks (vectors + metadata)

## Error Handling

**Missing Files**: Parser skips and returns empty list
**Invalid JSON**: `json.JSONDecodeError` → skip file
**ONNX Load Failure**: Lazy load, first query raises exception
**No Results**: Returns empty list (client handles gracefully)
**Stale Index**: Automatic rebuild on upsert (atomic)

