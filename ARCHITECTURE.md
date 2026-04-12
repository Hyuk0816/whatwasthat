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
         │  Chunker (Multi-granularity, 3 scales)      │
         │  ├─ turn-pair   (2 turns)                   │
         │  ├─ small-window (2-6 turns, overlap 2)     │
         │  └─ session-outline (whole session, ≥4 turns)│
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
         │  Lightweight Reranker (v1.1)                │
         │  ├─ Query class: decision|code|overview|gen │
         │  ├─ Boost: mode align + term overlap + gran │
         │  └─ Overlap dedup penalty (-0.10)           │
         │                                              │
         │  Search Modes                                │
         │  ├─ default: Hybrid vector + BM25 + rerank  │
         │  ├─ decision: Pattern boost (1.3x)          │
         │  └─ code: Code snippet filter               │
         └─────────────────────────┬────────────────────┘
                                   │
         ┌─────────────────────────▼────────────────────┐
         │       Storage Layer (dual store)             │
         ├──────────────────────────────────────────────┤
         │  ChromaDB — search index                     │
         │  ├─ Distance: cosine                        │
         │  ├─ Index: HNSW                             │
         │  ├─ Payload: search_text + chunk metadata   │
         │  └─ Path: ~/.wwt/data/vector/               │
         │                                              │
         │  SQLite — RawSpan store (v1.0.12+)          │
         │  ├─ Full raw_text per span                  │
         │  ├─ Full code_snippets                      │
         │  └─ Fetched by recall_chunk via span_id     │
         │                                              │
         │  Chunk metadata (Chroma)                     │
         │  ├─ session_id, span_id, granularity        │
         │  ├─ project, project_path, git_branch       │
         │  ├─ source (platform), timestamp            │
         │  ├─ turn_count, raw_length                  │
         │  └─ code_count, code_languages, snippet_ids │
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

### 3. Chunking Phase (v1.1 multi-granularity)

**Input**: `list[Turn]` + `SessionMeta`

`chunk_turns()` produces chunks at **three granularities simultaneously** from the same turn list, so the right-sized context can win at search time.

| Granularity | Window | Overlap | Chunk ID key | Span ID key | Notes |
|---|---|---|---|---|---|
| `turn-pair` | 2 turns | none (step 2) | `tp{start}` | `tp{start}e{end}` | Fact recall |
| `small-window` | 2–6 turns (sliding) | 2 turns (step 4) | `c{start}` | `s{start}e{end}` | Decision context |
| `session-outline` | whole session (≥4 turns) | — | `outline` | `outline` | Session overview; turns truncated to first 200 chars |

**Example (10 turns)**

```
[T0 T1 T2 T3 T4 T5 T6 T7 T8 T9]

turn-pair         : [T0 T1] [T2 T3] [T4 T5] [T6 T7] [T8 T9]
small-window      : [T0..T5]           [T4..T9]
session-outline   : [T0..T9] (each turn trimmed to 200 chars)
```

**Chunk Validation**

A chunk is kept if:
1. It contains ≥ 1 user turn.
2. Raw text ≥ 200 chars — **enforced for `turn-pair` and `small-window`**; `session-outline` skips this check so short sessions still get an overview.
3. For `small-window`: turns ≥ `min_turns` (default 2).
4. `session-outline` additionally requires the session to have ≥ 4 turns (`_MIN_OUTLINE_TURNS`).

**Chunk ID Generation** (deterministic, idempotent upsert)

```python
chunk_id = sha256(f"{session_id}:{key}").hexdigest()[:16]
# key ∈ {"tp{start}", "c{start}", "outline"}
```

The prefix scheme (`tp` / `c` / `outline`) guarantees no collisions across granularities within the same session.

**Chunk Metadata**

```python
{
  "session_id":     str,
  "granularity":    str,            # "turn-pair" | "small-window" | "session-outline"
  "span_id":        str,            # Points into RawSpan SQLite
  "start_turn_index": int,
  "end_turn_index":   int,
  "turn_count":     int,
  "raw_length":     int,            # Full raw text length
  "project":        str,            # From cwd basename
  "project_path":   str,            # Full cwd
  "git_branch":     str,
  "source":         str,            # "claude-code" | "gemini-cli" | "codex-cli"
  "timestamp":      str,            # ISO format
  "code_count":     int,            # # of snippets in span
  "code_languages": list[str],      # Sorted unique languages
  "snippet_ids":    list[str],      # Code snippet IDs in RawSpan
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

Sort by hybrid, keep top (top_k * 2) → pass to reranker
```

**Step 4: Lightweight Reranking (v1.1)**

After hybrid scoring, candidates are reranked with cheap feature matching — no extra model call. `search()` over-fetches (`top_k * 2`), reranks, then trims to `top_k`.

```
1. Classify query:
     _classify_query(query) → "decision" | "code" | "overview" | "general"
       - decision : Korean/English decision patterns (대신, 선택, 이유 / instead of, because, ...)
       - code     : Error or code-shaped tokens (stack trace, traceback, TypeError, ...)
       - overview : "overall", "전반", "summary", ...
       - general  : fallback

2. For each candidate, compute boost (capped at +0.25):
     (a) Query-mode alignment (+0.08)
           decision query → chunk.search_text matches decision pattern
           code query     → chunk.code_count > 0
     (b) Exact term overlap (up to +0.08)
           boost += (matched_tokens / |query_tokens|) * 0.08
     (c) Granularity preference (+0.05)
           decision → small-window
           code     → turn-pair
           overview → session-outline

     score' = min(score + boost, 1.0)

3. Overlap dedup penalty:
     For every pair (A, B) in the same session where
       turn_range_overlap(A, B) / min(turn_count) ≥ 0.5
     subtract 0.10 from the lower-scoring one (clamped ≥ 0).

4. Sort by reranked score, return top top_k.
```

This keeps the decision-ish / code-ish / overview-ish chunks in front when the query looks that way, while preventing near-duplicate adjacent windows from hogging the top slots.

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

**Chunk**: Searchable unit for indexing (v1.1)
- `id`: Deterministic chunk ID (sha256[:16])
- `span_id`: Pointer to the `RawSpan` row in SQLite
- `session_id`: Parent session
- `granularity`: `"turn-pair"` | `"small-window"` | `"session-outline"`
- `start_turn_index`, `end_turn_index`, `turn_count`
- `search_text`: Text used for embedding + BM25
- `raw_preview`: First 1000 chars of the raw span (for result preview)
- `raw_length`: Full raw text length
- `project`, `project_path`, `git_branch`, `source`, `timestamp`: Metadata
- `snippet_ids`, `code_count`, `code_languages`: Code snippet pointers

**RawSpan**: Full-fidelity original text, stored in SQLite
- `id`: `{session_id}:{span_key}` (e.g. `...:s4e9`, `...:tp0e1`, `...:outline`)
- `session_id`, `start_turn_index`, `end_turn_index`
- `raw_text`: Complete, untruncated
- `code_snippets`: Full code blocks (not just metadata)
- `snippet_ids`: Parallel to `code_snippets`

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

