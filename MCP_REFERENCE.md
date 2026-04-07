# WWT MCP Reference

## Overview

WWT provides an MCP (Model Context Protocol) server for integration with Claude Code, Gemini CLI, and Codex CLI. After `wwt setup`, LLMs can search conversation logs using natural language.

**Server Info**
- Name: `whatwasthat`
- Binary: `wwt-mcp`
- Registration: Global (`~/.claude/mcp_servers.json`, etc.)
- Status: Automatically configured by `wwt setup`

## Tools

### search_memory

Search past conversations with optional filters (project, platform, branch).

**Signature**
```python
def search_memory(
    query: str,
    project: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
    git_branch: str | None = None,
) -> str
```

**Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | str | Yes | Search query (natural language) |
| `project` | str | No | Project name filter (fuzzy match) |
| `cwd` | str | No | Current working directory (auto-detect project name) |
| `source` | str | No | Platform filter: `"claude-code"`, `"gemini-cli"`, `"codex-cli"` |
| `git_branch` | str | No | Git branch filter |

**Filter Logic**

- If `project` is provided → use it
- Else if `cwd` is provided AND `source` and `git_branch` are both None → extract project name from cwd basename
- Else → search across all projects

**Returns**

String with formatted results:
```
N개 세션에서 관련 기억을 찾았습니다:

1. project-name (branch) [platform] (점수: 0.93)
   [user]: User message
   [assistant]: Assistant response

2. ...
```

**Examples**

**Example 1: Search with project filter**
```
LLM: search_memory(
  query="Redis 캐시 설정",
  project="backend-api"
)

Output:
2개 세션에서 관련 기억을 찾았습니다:

1. backend-api (main) [claude-code] (점수: 0.91)
   [user]: Redis 캐시 TTL 어떻게 설정해?
   [assistant]: expire 시간을 3600초로 설정하고...

2. backend-api (feature/cache) [codex-cli] (점수: 0.84)
   [user]: 캐시 무효화 정책 어떻게 하지?
   [assistant]: TTL 기반 + pub/sub...
```

**Example 2: Search by platform only**
```
LLM: search_memory(
  query="JWT 인증",
  source="gemini-cli"
)

Output:
1개 세션에서 관련 기억을 찾았습니다:

1. auth-service (main) [gemini-cli] (점수: 0.88)
   [user]: JWT 토큰 갱신 로직 구현해줘
   [assistant]: refreshToken을 httpOnly 쿠키에...
```

**Example 3: Auto-detect project from cwd**
```
LLM: search_memory(
  query="Docker 최적화",
  cwd="/Users/user/projects/frontend"
)

# Extracts project name "frontend" from cwd
# Searches only "frontend" project

Output:
1개 세션에서 관련 기억을 찾았습니다:

1. frontend (main) [claude-code] (점수: 0.79)
   [user]: Dockerfile 최적화 좀 해줘
   [assistant]: multi-stage build로 변경하면...
```

**Example 4: Search with branch filter**
```
LLM: search_memory(
  query="마이그레이션",
  project="backend-api",
  git_branch="main"
)

Output:
1개 세션에서 관련 기억을 찾았습니다:

1. backend-api (main) [claude-code] (점수: 0.85)
   [user]: PostgreSQL 마이그레이션 스크립트 작성해줄래?
   [assistant]: Alembic을 사용하면 좋습니다...
```

**When to Use**

- User mentions specific project: use `project`
- User mentions specific platform (Claude/Gemini/Codex): use `source`
- User mentions specific branch: use `git_branch`
- User mentions multiple filters: combine them (AND logic)
- User provides cwd in context: use `cwd` for auto-detection

**Behavior**

- Returns top matching sessions (grouped by session_id)
- Each session shows its best 3 matching chunks
- Scores are 0-1 (1.0 = perfect match)
- Minimum score threshold: 0.5 (below ignored)

---

### search_all

Search across all conversations without filters.

**Signature**
```python
def search_all(query: str) -> str
```

**Parameters**

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `query` | str | Yes | Search query (natural language) |

**Returns**

String with formatted results (same format as `search_memory`).

**Examples**

**Example 1: Cross-project search**
```
LLM: search_all(query="Docker multi-stage build")

Output:
3개 세션에서 관련 기억을 찾았습니다:

1. backend-api (main) [claude-code] (점수: 0.93)
   [user]: Dockerfile 최적화 좀 해줘
   [assistant]: multi-stage build로 변경하면 이미지 크기를 70%...

2. infra (devops) [gemini-cli] (점수: 0.85)
   [user]: CI/CD 파이프라인에서 빌드 시간 줄이는 법
   [assistant]: Docker layer 캐싱과 BuildKit을...

3. frontend (main) [codex-cli] (점수: 0.79)
   [user]: 프론트엔드 Docker 이미지 경량화
   [assistant]: nginx:alpine 기반으로 빌드...
```

**Example 2: Cross-platform search**
```
LLM: search_all(query="PostgreSQL 인덱스 최적화")

Output:
2개 세션에서 관련 기억을 찾았습니다:

1. backend-api (main) [claude-code] (점수: 0.90)
   [user]: PostgreSQL 쿼리 성능 개선해줄래?
   [assistant]: 인덱스를 composite key로...

2. data-pipeline (main) [gemini-cli] (점수: 0.82)
   [user]: 데이터베이스 마이그레이션 시 인덱스 최적화 필요
   [assistant]: B-tree 인덱스 선택이 중요합니다...
```

**When to Use**

- User asks without mentioning specific project or platform
- User wants to find similar solutions across all projects
- User is exploring past work across multiple projects
- General cross-project knowledge retrieval

**Behavior**

Same as `search_memory`, but no project/source/branch filtering.

---

### search_decision

Search for decision-making context (why decisions were made).

**Signature**
```python
def search_decision(
    query: str,
    project: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
    git_branch: str | None = None,
) -> str
```

**Parameters**

Same as `search_memory`.

**Returns**

String with decision-focused results (same format as `search_memory`).

**Decision Patterns**

Boosts (1.3×) chunks containing decision language:

- Korean: "대신", "선택", "결정", "이유", "비교", "으로 갔", "하기로", "보다", "때문에", "장단점"
- English: "instead of", "chose", "decided", "because", "compared", "trade-off", "prefer", "rather than"

**Examples**

**Example 1: Why a technology was chosen**
```
LLM: search_decision(
  query="왜 Redis 대신 MongoDB를 선택했지?",
  project="cache-service"
)

Output:
1개 세션에서 의사결정 기억을 찾았습니다:

1. cache-service (main) [claude-code] (점수: 0.92)
   [user]: MongoDB vs Redis 중 뭘 선택하지?
   [assistant]: Redis를 선택했습니다. 이유는:
             - 메모리 기반으로 속도 우선
             - TTL 관리가 간단
             - 우리 사용 패턴은 복잡한 쿼리 불필요
```

**Example 2: Why architecture was changed**
```
LLM: search_decision(
  query="왜 모놀리식 아키텍처에서 마이크로서비스로 갔지?",
  project="backend-api"
)

Output:
1개 세션에서 의사결정 기억을 찾았습니다:

1. backend-api (main) [claude-code] (점수: 0.88)
   [user]: 마이크로서비스 아키텍처로 리팩토링할까?
   [assistant]: 마이크로서비스로 전환했습니다. 장단점:
             장점: 팀별 독립 배포, 기술 다양화
             단점: 네트워크 복잡도, 운영 오버헤드
             선택 이유: 팀 성장 + 배포 빈도 증가
```

**When to Use**

- User asks "왜...?" or "why...?" questions
- User wants to understand past architectural decisions
- User wants to avoid repeating past mistakes
- User needs decision rationale for similar problems

**Behavior**

Filters for decision-related language, giving higher scores to chunks with "chose", "decided", "trade-off", etc.

---

### ingest_session

Manually ingest conversation logs into the vector database.

**Signature**
```python
def ingest_session(path: str) -> str
```

**Parameters**

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `path` | str | Yes | JSONL/JSON file path or directory path |

**Returns**

String with ingestion summary:
```
완료: N 세션, M 청크 (K 신규 임베딩)
```

**Examples**

**Example 1: Ingest single file**
```
LLM: ingest_session("/Users/user/.claude/projects/my-project/sessions/session-abc.jsonl")

Output:
완료: 1 세션, 24 청크 (12 신규 임베딩)
```

**Example 2: Ingest directory**
```
LLM: ingest_session("/Users/user/.claude/projects/")

Output:
완료: 120 세션, 2340 청크 (340 신규 임베딩)
```

**Behavior**

- Auto-detects file format (Claude Code JSONL, Gemini JSON/JSONL, Codex JSONL)
- Skips duplicate chunks (same session_id + turn_count)
- Defers BM25 rebuild for bulk ingest (auto-rebuild at end)
- Thread-safe (can be called multiple times)

**When to Use**

- User manually adds new session files
- Manual upload from another machine
- Batch import of exported sessions
- Recovery from backup

---

## Resource

### project_context

Get recent decision-making context for a project (max 2000 tokens).

**URI Pattern**
```
wwt://project/{project}/context
```

**Parameters**

| Parameter | Type | Description |
|----------|------|-------------|
| `project` | str | Project name |

**Returns**

String with recent decision context:
```
# {project} — 최근 의사결정 맥락

- [Summary of recent decision 1]
- [Summary of recent decision 2]
- [Summary of recent decision 3]
```

**Example**

```
Resource: wwt://project/backend-api/context

Output:
# backend-api — 최근 의사결정 맥락

- Redis를 선택했습니다. TTL 기반 캐싱으로 성능 70% 개선
- PostgreSQL에서 MongoDB로 마이그레이션 완료. 문서 기반 구조가 더 유연함
- 마이크로서비스 아키텍처로 전환. 팀별 독립 배포 가능
```

**Behavior**

- Searches for decision-related content in project
- Returns top 3 most recent significant decisions
- Summarized to fit within 2000 tokens
- Empty if no decision history found

---

## MCP Server Setup

### Register Server

After `wwt setup`, the MCP server is automatically registered:

**Claude Code** (`~/.claude/mcp_servers.json`)
```json
{
  "mcpServers": {
    "whatwasthat": {
      "command": "wwt-mcp"
    }
  }
}
```

**Gemini CLI** (`~/.gemini/mcp_servers.json`)
```json
{
  "mcpServers": {
    "whatwasthat": {
      "command": "wwt-mcp"
    }
  }
}
```

**Codex CLI** (`.codex/mcp_servers.json` or via config)
```json
{
  "mcpServers": {
    "whatwasthat": {
      "command": "wwt-mcp"
    }
  }
}
```

### Verify Registration

```bash
# Claude Code
claude mcp list

# Gemini CLI
gemini mcp list

# Codex CLI
codex mcp list
```

Should show: `whatwasthat` server running

### Manual Registration

If `wwt setup` fails, register manually:

```bash
# Claude Code
claude mcp add whatwasthat --scope user -- wwt-mcp

# Gemini CLI
gemini mcp add whatwasthat wwt-mcp --scope user

# Codex CLI
codex mcp add whatwasthat -- wwt-mcp
```

---

## LLM Instructions

The MCP server includes these instructions (auto-sent to LLM):

> 세션 시작 시, 현재 프로젝트의 최근 기술 결정사항을 검색하여 컨텍스트를 파악하세요. search_memory(query='recent technical decisions and architecture choices')를 호출하세요. 사용자가 과거 대화, 이전 작업, 의사결정 이유를 물을 때도 이 도구를 사용하세요. 예: '그때 그거 뭐였지?', '이전에 어떻게 했지?', '왜 Redis를 선택했지?' 등. search_memory는 현재 프로젝트 맥락으로, search_all은 모든 프로젝트에서, search_decision은 의사결정 맥락(왜 A 대신 B를 선택했는지)을 검색합니다.

Translation:

> At session start, search for recent technical decisions in the current project to understand context. Call search_memory(query='recent technical decisions and architecture choices'). When users ask about past conversations, previous work, or decision rationale, use these tools. Examples: 'What was that?', 'How did we do this before?', 'Why did we choose Redis?'. search_memory searches current project context; search_all searches across all projects; search_decision searches decision context (why A was chosen over B).

---

## Error Handling

### No Results Found

```
관련 기억을 찾지 못했습니다.
```

**Causes**
- Database not initialized
- No chunks matching query (score < 0.5)
- All projects filtered out (project/source/branch mismatch)

**Resolution**
- Run `wwt setup` to initialize
- Run `wwt ingest` to add data
- Try broader query or `search_all`

### Unsupported File Format

```
지원하지 않는 파일 형식: /path/to/file
```

**Causes**
- File is not `.jsonl` or `.json`
- File format not recognized (not Claude/Gemini/Codex)
- File is empty or corrupted

**Resolution**
- Verify file format
- Try parsing manually: `python -m json.tool file.jsonl`
- Use correct log export format

### Database Connection Error

Rare, indicates corrupted ChromaDB:

**Resolution**
```bash
wwt reset
wwt setup
```

---

## Performance

| Operation | Time | Notes |
|-----------|------|-------|
| search_memory (typical) | 100-200ms | Hybrid vector + BM25 |
| search_decision | 100-200ms | Same as search_memory + pattern boost |
| ingest_session (100 chunks) | ~5s | Includes embedding |
| project_context | 100-150ms | Cached after first query |

---

## Best Practices

### LLM Prompting

**When to use each tool:**

| User Query | Tool | Parameters |
|-----------|------|------------|
| "Redis 캐시 설정 어떻게 했지?" | search_memory | project=auto-detect from cwd |
| "다른 프로젝트에서 Docker 최적화" | search_all | query only |
| "왜 MongoDB 선택했지?" | search_decision | project=auto-detect |
| "Codex에서 JWT 구현" | search_memory | source="codex-cli" |
| "main 브랜치에서 auth 작업" | search_memory | git_branch="main" |

### Query Optimization

- **Be specific**: "Redis TTL 설정" better than "캐싱"
- **Use natural language**: "왜 A 대신 B를 선택했지?" works
- **Combine filters**: project + branch for precise results
- **Fallback to search_all**: If search_memory returns nothing

### Bulk Operations

After ingesting large datasets, give BM25 index time to rebuild:

```
LLM: ingest_session("/path/to/large/dataset/")

# Wait 10-30 seconds before searching
# Then use search_memory/search_all
```

