# What was that?!

> **"그때 그거 뭐였지?"** — AI 대화 기억을 검색하는 시맨틱 엔진

[![PyPI version](https://badge.fury.io/py/whatwasthat.svg)](https://pypi.org/project/whatwasthat/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

---

## 문제

AI와 중요한 대화를 하고, 기술적 결정을 내리고, 삽질 끝에 해결책을 찾았는데 — 다음 세션에서 AI는 아무것도 기억하지 못합니다.

- "전에 Redis 캐시 설정 어떻게 했었지?"
- "다른 프로젝트에서 mTLS 인증서 어떻게 구성했지?"
- "지난번에 비슷한 버그 어떻게 고쳤지?"

물론 `.md` 파일에 기록은 합니다. 그리고 그 파일은 조용히 쌓여갑니다. 그리고 우리는 절대 다시 열어보지 않습니다.

매번 같은 설명을 반복하거나, 대화 로그를 직접 뒤지고 있다면 — WWT가 해결합니다.

## 해결

WWT는 여러 AI 코딩 에이전트(Claude Code, Gemini CLI, Codex CLI)의 대화 로그를 자동으로 파싱하고, 시맨틱 벡터로 변환하여 **자연어로 과거 대화를 통합 검색**할 수 있게 합니다.

```
세션 종료 → 대화 로그 자동 수집 → 파싱 → 청킹 → 벡터화 → 검색 가능
```

### 크로스 프로젝트 검색

프로젝트 A에서 했던 삽질이 프로젝트 B에서 또 필요할 때가 있습니다. WWT는 모든 프로젝트의 대화를 한곳에 모아두기 때문에, **프로젝트 경계를 넘어 검색**할 수 있습니다.

```
사용자: "전에 다른 프로젝트에서 Docker multi-stage build 어떻게 설정했지?"
WWT: [프로젝트 A] Dockerfile 최적화 대화 → 빌드 시간 70% 단축한 설정
     [프로젝트 C] CI/CD 파이프라인 대화 → 캐시 레이어 최적화 방법
```

기본적으로 현재 프로젝트 맥락에서 검색하지만, `--all` 플래그로 전체 프로젝트를 검색할 수 있습니다.

### 크로스 플랫폼 검색

Claude Code에서 했던 대화를 Codex CLI에서 찾을 수도 있습니다. 모든 플랫폼의 대화가 하나의 벡터 DB에 통합되기 때문에, **어떤 플랫폼에서 검색하든 모든 플랫폼의 기억**에 접근할 수 있습니다.

```
사용자 (Codex CLI에서): "지난번에 Claude Code로 작업할 때 JWT 인증 어떻게 구현했지?"
WWT: [claude-code] JWT 토큰 갱신 로직 구현 대화 발견
     [gemini-cli] 비슷한 OAuth 플로우 논의 발견
```

## 주요 특징

- **하이브리드 검색**: 벡터 시맨틱 검색(60%) + BM25 키워드 검색(40%) 조합
- **한국어 최적화**: kiwipiepy 형태소 분석 기반 토크나이징
- **프로젝트별 격리**: 프로젝트 단위 필터링 + 전체 프로젝트 크로스 검색
- **크로스 플랫폼**: Claude Code, Gemini CLI, Codex CLI 대화 로그 통합 검색
- **MCP 서버 내장**: Claude Code/Gemini CLI/Codex CLI에서 자연어로 바로 검색
- **완전 로컬**: 클라우드 API 호출 없음, 데이터가 내 컴퓨터를 떠나지 않음
- **자동 수집**: 각 플랫폼 Hook으로 세션 종료 시 자동 적재
- **원커맨드 설정**: `wwt setup` 한 번으로 DB + Hook + MCP 전부 설정 (모든 플랫폼)

---

## 아키텍처

```
┌──────────────────────────────────────────┐
│   CLI (typer)    │    MCP Server (FastMCP)│
│   wwt search     │    search_memory       │
│   wwt ingest     │    search_all          │
└────────┬─────────┴──────────┬────────────┘
         │                    │
    ┌────▼────┐         ┌────▼─────┐
    │ Pipeline │         │  Search  │
    ├──────────┤         ├──────────┤
    │ Parser   │         │ Engine   │  세션 그룹핑
    │ Chunker  │         │ Vector   │  하이브리드 검색
    └────┬─────┘         └────┬─────┘
         │                    │
         └────────┬───────────┘
                  │
          ┌───────▼────────┐
          │    ChromaDB    │
          │  HNSW + BM25   │
          │ ~/.wwt/data/   │
          └────────────────┘
```

### 데이터 플로우

```
JSONL 대화 로그
  ↓ Parser: 코드블록·시스템태그 제거, 의미 없는 짧은 턴 필터링
Turn 시퀀스
  ↓ Chunker: 슬라이딩 윈도우 (2-6턴, 2턴 오버랩)
Chunk 리스트
  ↓ SentenceTransformer: multilingual-e5-small 임베딩
벡터 + 메타데이터
  ↓ ChromaDB: HNSW 인덱스 저장
검색 가능 상태
```

---

## 설치

### pip

```bash
pip install whatwasthat
```

### uv (권장)

```bash
uv tool install whatwasthat
```

### 초기 설정

```bash
# DB 초기화 + Stop Hook + MCP 서버 자동 등록 (원커맨드)
wwt setup
```

이 명령 하나로:
1. ChromaDB 벡터 데이터베이스 초기화 (`~/.wwt/data/vector/`)
2. 각 플랫폼 Hook 스크립트 설치 (세션 종료 시 자동 적재)
3. 설치된 모든 플랫폼에 MCP 서버 등록 (Claude Code, Gemini CLI, Codex CLI)
4. 기존 대화 로그 자동 검색 및 적재

> 이미 적재된 대화는 중복 처리되지 않습니다. 증분 upsert 방식으로 변경된 청크만 임베딩하고, 기존 데이터는 건너뜁니다. `wwt setup`을 여러 번 실행해도 안전합니다.

> 임베딩 모델(`multilingual-e5-small`, ~470MB)은 **최초 실행 시** HuggingFace에서 자동 다운로드됩니다.

---

## 사용법

### 각 플랫폼에서 설정하기

| 플랫폼 | 셸 실행 방법 | 설정 명령 |
|--------|------------|----------|
| **터미널** | 직접 실행 | `wwt setup` |
| **Claude Code** | `!` 접두사 | `! wwt setup` |
| **Gemini CLI** | 자연어 요청 | `"wwt setup 실행해줘"` |
| **Codex CLI** | 자연어 요청 | `"wwt setup 실행해줘"` |

어떤 플랫폼에서 실행하든 설치된 모든 플랫폼의 MCP + Hook + 기존 대화가 자동 설정됩니다.

### CLI

```bash
# 대화 로그 수동 적재
wwt ingest ~/.claude/projects/my-project/sessions/

# 단일 파일 적재
wwt ingest ~/session-abc123.jsonl

# 현재 프로젝트 맥락으로 검색
wwt search "Redis 캐시 설정 어떻게 했지?"

# 의사결정 맥락 검색 — 왜 그렇게 했는지?
wwt why "왜 Redis를 선택했지?"

# 특정 프로젝트에서 검색
wwt search "mTLS 인증서 설정" --project keylink_service

# 전체 프로젝트 검색
wwt search "비슷한 버그 해결 방법" --all

# 모든 적재 데이터 삭제
wwt reset
```

### MCP (Claude Code / Gemini CLI / Codex CLI)

`wwt setup` 이후 MCP를 지원하는 모든 플랫폼에서 자연어로 바로 사용:

```
사용자: "전에 PostgreSQL 인덱스 최적화 어떻게 했었지?"
AI: [search_memory 자동 호출] → 모든 플랫폼의 관련 대화 3개 찾음
```

**MCP 도구:**

| 도구 | 용도 | 필터 옵션 |
|------|------|----------|
| `search_memory` | 프로젝트/플랫폼/브랜치 조건부 검색 | `project`, `source`, `git_branch`, `cwd` |
| `search_all` | 조건 없이 전체 통합 검색 | 없음 |
| `search_decision` | 의사결정 맥락 검색 ("왜 A 대신 B?") | `project`, `source`, `git_branch`, `cwd` |
| `ingest_session` | 대화 로그 수동 적재 | `path` |

LLM이 사용자 발화에서 자동으로 적절한 도구와 필터를 선택합니다:

**예시 1 — 플랫폼 필터 (`source`)**
```
사용자: "Codex에서 했던 Redis 캐시 설정 어떻게 했지?"
AI: [search_memory(query="Redis 캐시 설정", source="codex-cli") 호출]

→ 2개 세션에서 관련 기억을 찾았습니다:

  1. backend-api (main) [codex-cli] @ 2026-03-15 14:20 (점수: 0.91)
     [user]: Redis 캐시 TTL 어떻게 설정해?
     [assistant]: expire 시간을 3600초로 설정하고, invalidation은 이벤트 기반으로...

  2. backend-api (feature/cache) [codex-cli] @ 2026-03-10 09:45 (점수: 0.84)
     [user]: 캐시 무효화 정책 어떻게 하지?
     [assistant]: TTL 기반 + pub/sub 이벤트 조합이 가장 안정적입니다...
```

**예시 2 — 프로젝트 + 브랜치 필터**
```
사용자: "frontend 프로젝트 main 브랜치에서 인증 관련 작업한 거 찾아줘"
AI: [search_memory(query="인증", project="frontend", git_branch="main") 호출]

→ 1개 세션에서 관련 기억을 찾았습니다:

  1. frontend (main) [claude-code] @ 2026-04-01 16:30 (점수: 0.88)
     [user]: JWT 토큰 갱신 로직 구현해줘
     [assistant]: refreshToken을 httpOnly 쿠키에 저장하고, accessToken 만료 시...
```

**예시 3 — 필터 없이 전체 검색**
```
사용자: "전에 Docker multi-stage build 어떻게 했었지?"
AI: [search_all(query="Docker multi-stage build") 호출]

→ 3개 세션에서 관련 기억을 찾았습니다:

  1. backend-api (main) [claude-code] @ 2026-03-20 11:15 (점수: 0.93)
     [user]: Dockerfile 최적화 좀 해줘
     [assistant]: multi-stage build로 변경하면 이미지 크기를 70% 줄일 수 있습니다...

  2. infra (devops) [gemini-cli] @ 2026-03-18 15:40 (점수: 0.85)
     [user]: CI/CD 파이프라인에서 빌드 시간 줄이는 법
     [assistant]: Docker layer 캐싱과 BuildKit을 활용하면...

  3. frontend (main) [codex-cli] @ 2026-03-12 09:20 (점수: 0.79)
     [user]: 프론트엔드 Docker 이미지 경량화
     [assistant]: nginx:alpine 기반으로 빌드 스테이지 분리하면...
```

### 자동 수집 (Hook)

`wwt setup`을 실행하면 각 플랫폼에 맞는 Hook이 자동 설치됩니다:

| 플랫폼 | Hook 종류 | 동작 |
|--------|----------|------|
| **Claude Code** | Stop Hook | 매 응답 완료 시 비동기 적재 |
| **Gemini CLI** | AfterAgent Hook | 에이전트 완료 시 자동 적재 |
| **Codex CLI** | Stop Hook | 매 응답 완료 시 비동기 적재 |

별도 조작 없이 대화가 쌓입니다.

---

## 검색 엔진 상세

### 하이브리드 검색 전략

단일 검색 방식의 한계를 보완하기 위해 두 가지 검색을 조합합니다:

| 검색 방식 | 가중치 | 강점 | 약점 |
|-----------|--------|------|------|
| **벡터 검색** (HNSW, cosine) | 60% | 의미적 유사도, 패러프레이즈 매칭 | 정확한 키워드 놓침 |
| **BM25 키워드 검색** | 40% | 정확한 용어 매칭, 고유명사 | 의미적 변형 놓침 |

**예시:**
- "DB 설정 방법" → 벡터 검색이 "PostgreSQL 인덱스 구성" 매칭
- "FastAPI" → BM25가 정확한 키워드 매칭
- 두 결과를 합산하여 최종 순위 결정

### 한국어 토크나이징

kiwipiepy 형태소 분석기를 사용하여 한국어 특성을 반영합니다:

```
"PostgreSQL 인덱스를 최적화했습니다"
  ↓ CamelCase 분리: "Postgre SQL"
  ↓ 형태소 분석: ["postgre", "sql", "인덱스", "최적화"]
  ↓ 불용어 제거 (조사, 어미 등)
```

### 청킹 전략

대화를 의미 단위로 분할하되, 문맥이 끊기지 않도록 오버랩을 둡니다:

```
대화: [T1, T2, T3, T4, T5, T6, T7, T8, T9, T10]

청크 1: [T1, T2, T3, T4, T5, T6]     ← 6턴
청크 2:         [T5, T6, T7, T8, T9, T10]  ← 2턴 오버랩
```

- 윈도우 크기: 2~6턴
- 오버랩: 2턴 (문맥 보존)
- 최소 조건: 사용자 턴 1개 이상, 200자 이상

---

## 임베딩 모델 선정

### 선정 기준

| 기준 | 설명 |
|------|------|
| **다국어 지원** | 한국어 + 영어 혼합 대화 처리 필수 |
| **로컬 실행** | GPU 없이 CPU에서 실용적 속도 |
| **모델 크기** | 설치 부담 최소화 (1GB 이하) |
| **임베딩 품질** | 대화 맥락의 시맨틱 유사도 정확도 |

### 후보 모델 비교

| 모델 | 파라미터 | 크기 | 차원 | 다국어 | MTEB 평균 | 선정 |
|------|---------|------|------|--------|-----------|------|
| `multilingual-e5-small` | 118M | ~470MB | 384 | 100+ 언어 | 57.5 | **채택** |
| `multilingual-e5-base` | 278M | ~1.1GB | 768 | 100+ 언어 | 59.5 | 크기 부담 |
| `multilingual-e5-large` | 560M | ~2.2GB | 1024 | 100+ 언어 | 61.5 | 로컬 실행 비현실적 |
| `paraphrase-multilingual-MiniLM-L12-v2` | 118M | ~470MB | 384 | 50+ 언어 | 53.5 | e5 대비 품질 열세 |
| `bge-m3` | 568M | ~2.3GB | 1024 | 100+ 언어 | 62.0 | 크기 과대 |
| `all-MiniLM-L6-v2` | 22M | ~90MB | 384 | 영어만 | 56.3 | 한국어 미지원 |

### 선정 근거: `multilingual-e5-small`

1. **크기 vs 성능 최적점**: 470MB로 e5-base(1.1GB) 대비 절반 크기, MTEB 점수 차이 2점
2. **100+ 언어 지원**: 한국어-영어 코드스위칭 대화에 적합
3. **384차원**: ChromaDB HNSW 인덱스에서 메모리/속도 효율적
4. **CPU 추론 실용적**: M1 MacBook 기준 ~50ms/query
5. **SentenceTransformer 호환**: ChromaDB 내장 임베딩 함수로 바로 사용

### 임베딩 품질 실험 (한국어 대화)

```
Query: "Redis 캐시 TTL 설정"

multilingual-e5-small:
  ✓ "Redis expire 시간을 3600초로 설정했습니다" (0.87)
  ✓ "캐시 무효화 정책을 TTL 기반으로 변경" (0.82)
  ✗ "메모리 캐시 구현" (0.51) — 관련은 있지만 낮은 점수

paraphrase-multilingual-MiniLM:
  ✓ "Redis expire 시간을 3600초로 설정했습니다" (0.79)
  △ "캐시 무효화 정책을 TTL 기반으로 변경" (0.64)
  ✗ "메모리 캐시 구현" (0.58) — 노이즈 높음
```

e5-small이 관련 문서에 더 높은 점수를, 비관련 문서에 더 낮은 점수를 부여하여 **검색 정밀도가 우수**합니다.

---

## 설치 요구사항

### 시스템

- **Python**: 3.12+
- **OS**: macOS, Linux (Windows 미테스트)
- **디스크**: ~1.4GB (의존성 + 임베딩 모델)
- **RAM**: ~2GB (검색 시)

### 의존성 크기 상세

| 패키지 | 크기 | 역할 |
|--------|------|------|
| `torch` | ~378MB | 텐서 연산 (임베딩 추론) |
| `kiwipiepy` + 모델 | ~114MB | 한국어 형태소 분석 |
| `scipy` | ~81MB | 수학 연산 |
| `onnxruntime` | ~64MB | 추론 최적화 |
| `transformers` | ~50MB | 모델 로딩 |
| `chromadb` | ~47MB | 벡터 DB |
| 기타 | ~200MB | sentence-transformers, grpc 등 |
| **임베딩 모델** (최초 실행) | ~470MB | HuggingFace 캐시 |

> 참고: PyPI 패키지 자체는 수백 KB입니다. 위 크기는 `pip install` 시 설치되는 의존성입니다.

---

## 데이터 저장 위치

```
~/.wwt/
├── data/
│   └── vector/          # ChromaDB 벡터 인덱스
└── ingest.log           # 자동 적재 로그

~/.cache/huggingface/
└── hub/
    └── models--intfloat--multilingual-e5-small/  # 임베딩 모델 캐시
```

---

## 설계 철학 — 왜 벡터 검색인가

지식 베이스를 구축하는 접근(LLM이 원시 자료를 요약/정리하여 위키를 만드는 방식)과 달리, WWT는 **원문 기반 벡터 검색**을 선택했습니다.

| | 원문 검색 (WWT) | 지식 컴파일 |
|---|---|---|
| **방식** | 원문을 벡터로 임베딩 → 유사도 검색 | LLM이 원시 자료를 요약/정리 |
| **원문 보존** | 원문 그대로 반환 | 요약 과정에서 정보 손실 가능 |
| **비용** | 임베딩 1회 (저렴) | 컴파일에 LLM 토큰 대량 소비 |
| **자동화** | Hook으로 자동 수집 | 새 자료마다 재컴파일 필요 |
| **확장성** | 수천 세션 처리 가능 | 지식 베이스가 커지면 컨텍스트 한계 |

**대화 기록 검색**에서 원문 검색이 적합한 이유:

1. **원문 보존이 핵심** — "정확히 뭐라고 했었지?"에 답하려면 요약이 아니라 원문이 필요
2. **자동 수집** — 대화가 끝날 때마다 자동으로 적재, 수동 개입 없음
3. **LLM이 정리** — WWT가 원문을 찾아주면, LLM이 컨텍스트를 읽고 정리해서 답변

```
유저: "전에 Redis 캐시 어떻게 했지?"
  → WWT: 관련 대화 원문 3개 반환
  → LLM: 원문을 읽고 "TTL 300초, invalidation은 이벤트 기반" 정리해서 답변
```

WWT는 **정확한 원문을 찾는 것**에 집중하고, **정리/요약은 LLM에게 맡깁니다.**

---

## 플랫폼 지원

| 플랫폼 | 자동 수집 | 검색 | 로그 포맷 |
|--------|----------|------|----------|
| **Claude Code** | Stop Hook | MCP + CLI | JSONL |
| **Gemini CLI** | AfterAgent Hook | MCP + CLI | JSON (`messages` 배열) |
| **Codex CLI** | Stop Hook | MCP + CLI | JSONL (RolloutItem) |

> 다운스트림(청킹, 임베딩, 검색)은 포맷 독립적입니다. `SessionParser` Protocol을 구현하면 새 플랫폼을 추가할 수 있습니다.

---

## 라이선스

이 프로젝트는 [Apache License 2.0](LICENSE) 라이선스를 따릅니다.
