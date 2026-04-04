# WWT 아키텍처 전환 계획: Triple 추출 → 청크 벡터화

> 작성일: 2026-04-05
> 상태: 설계 완료, 구현 대기

---

## 1. 현재 상태 및 문제점

### 현재 아키텍처 (Triple 기반)

```
JSONL → Parser → Chunker → Resolver → Extractor(Ollama) → GraphStore(Kuzu) + VectorStore(ChromaDB)
                                           ↑ 병목
```

### 문제점

**1. 추출 품질 한계**
- Qwen 3.5 4B → Gemma 4 E4B로 교체해도 5개 청크 중 2개만 트리플 추출 성공
- 핵심 기술 결정(Kuzu, ChromaDB 선택 등)이 누락되고, 시스템 메타데이터가 대신 추출됨
- Few-shot 프롬프트, 노이즈 필터링 등 튜닝해도 근본적 한계

**2. 속도**
- 청크당 30~50초 (Ollama LLM 추론)
- 세션 1개 ingest에 3~5분
- 대화 로그가 수백 개면 비현실적

**3. 사용자 배포 불가**
- Ollama 설치 + 10GB 모델 다운로드 필수
- 일반 사용자에게 "이 CLI 쓰려면 10GB 모델 받으세요"는 현실적이지 않음

**4. 정보 손실**
- 트리플 변환 과정에서 원문 맥락이 사라짐
- "그때 그거 뭐였지?"에 `Kuzu —[CHOSEN_OVER]→ PostgreSQL` 보다 실제 대화 맥락이 더 유용

**5. 검색 부정확**
- 벡터 검색 → 엔티티 매칭 → 그래프 세션 조회 → 트리플 필터링의 4단계 파이프라인
- 각 단계마다 정확도 손실 누적

---

## 2. 변경 방향 — 청크 벡터화 직행

### 새 아키텍처

```
JSONL → Parser → Chunker → VectorStore(ChromaDB)
                    ↓
              메타데이터 추출
              (project, git_branch, timestamp)
```

### Before vs After

| 항목 | Before (Triple) | After (Chunk Vector) |
|------|-----------------|---------------------|
| Ingest 속도 | 3~5분/세션 | **수 초/세션** |
| Ollama 필요 | 필수 (10GB) | **불필요** |
| 저장 단위 | 트리플 (s-p-o) | **청크 원문** |
| 검색 결과 | 구조화된 관계 | **실제 대화 맥락** |
| DB | Kuzu + ChromaDB | **ChromaDB만** |
| 임베딩 | 엔티티명만 | **청크 전체 텍스트** |

### 메타데이터 구조

JSONL 로그에서 직접 추출 (별도 LLM 불필요):

```python
{
    "session_id": "418c7b60-...",           # JSONL sessionId
    "project": "TipOfMyTongue",             # cwd에서 마지막 디렉토리명
    "project_path": "/Users/.../project",   # JSONL cwd
    "git_branch": "feature/auth",           # JSONL gitBranch
    "timestamp": "2026-04-03T00:06:08",     # JSONL 첫 메시지 timestamp
    "chunk_index": 0,                       # 청크 순서
    "turn_count": 6,                        # 청크 내 턴 수
}
```

### 검색 흐름

```
사용자 쿼리 "그때 DB 뭘로 했지?"
  → 쿼리 임베딩 (sentence-transformers, 로컬)
  → ChromaDB 유사도 검색 + BM25 키워드 검색 (Hybrid)
  → 선택적 필터: where={"project": "whatwasthat"}
  → 결과 청크를 session_id로 그루핑
  → 세션별 SearchResult 생성 (최고 스코어 기준 정렬)
```

### 컨텍스트 인식 검색 (MCP 연동)

```
1. 쿼리에 프로젝트명이 명시됨 → 해당 프로젝트로 필터
   "TipOfMyTongue에서 썼던 파서 방식 뭐였지?"
     → where={"project": "TipOfMyTongue"}

2. 프로젝트명 없음 → MCP가 현재 cwd 자동 감지하여 필터
   "그때 DB 뭘로 했지?"
     → MCP cwd=/Users/.../whatwasthat → where={"project": "whatwasthat"}

3. --all 플래그 → 전체 프로젝트 검색
```

### 검색 출력 예시

```
$ wwt search "DB 뭘로 했지?"

2개 세션에서 관련 기억을 찾았습니다:

  1. TipOfMyTongue (main) — 2026-04-03 (점수: 0.82)
     [user]: DB는 PostgreSQL 대신 Kuzu를 선택했어. 그래프 쿼리가 빨라서.
     [assistant]: 좋은 선택입니다. Kuzu는 임베디드 그래프 DB라...

  2. whatwasthat (feature/vector) — 2026-04-04 (점수: 0.71)
     [user]: 임베딩 벡터 저장은 ChromaDB로 했고.
     [assistant]: ChromaDB는 벡터 검색에 최적화되어 있습니다...
```

---

## 3. 데이터 모델

### 유지

```python
class Turn(BaseModel):
    role: str
    content: str
    timestamp: datetime | None = None
```

### 수정 — 메타데이터 추가

```python
class Chunk(BaseModel):
    id: str
    session_id: str
    turns: list[Turn]
    raw_text: str
    project: str = ""
    project_path: str = ""
    git_branch: str = ""
    timestamp: datetime | None = None
```

### 새로 추가

```python
class SessionMeta(BaseModel):
    session_id: str
    project: str
    project_path: str
    git_branch: str
    started_at: datetime
    turn_count: int = 0
```

### 수정 — 청크 원문 반환

```python
class SearchResult(BaseModel):
    session_id: str
    chunks: list[Chunk]       # triples → chunks
    summary: str
    score: float
    project: str = ""
    git_branch: str = ""
```

### 삭제

- `Triple` 모델
- `Entity` 모델

---

## 4. 파일 변경 목록

### 제거 (6개 파일)

| 파일 | 이유 |
|------|------|
| `pipeline/extractor.py` | Ollama LLM 호출 — 벡터화에 불필요 |
| `pipeline/prompts.py` | LLM 프롬프트 템플릿 |
| `pipeline/resolver.py` | 한국어 대명사 해소 — 트리플용 |
| `pipeline/entity.py` | 엔티티 중복 제거 — 트리플용 |
| `storage/graph.py` | Kuzu 그래프 DB — 트리플 저장소 |
| `server/mcp.py` | 미구현, Phase 3에서 새로 작성 |

### 수정 (7개 파일)

| 파일 | 변경 내용 |
|------|----------|
| `pipeline/parser.py` | 메타데이터(cwd, gitBranch, timestamp) 추출 추가 |
| `pipeline/chunker.py` | 메타데이터를 Chunk에 전달 |
| `storage/vector.py` | 청크 원문 + 메타데이터 저장으로 전환 |
| `search/engine.py` | 그래프 제거, 벡터 검색 → 청크 반환으로 단순화 |
| `models.py` | Triple/Entity 삭제, SessionMeta 추가, SearchResult 변경 |
| `config.py` | OLLAMA_MODEL, KUZU_DB_PATH 제거 |
| `cli/app.py` | 새 파이프라인 반영 |

### 테스트

| 파일 | 변경 |
|------|------|
| `test_pipeline/test_extractor.py` | 삭제 |
| `test_pipeline/test_resolver.py` | 삭제 |
| `test_pipeline/test_entity.py` | 삭제 |
| `test_storage/test_graph.py` | 삭제 |
| `test_pipeline/test_parser.py` | 메타데이터 추출 테스트 추가 |
| `test_storage/test_vector.py` | 청크 저장/검색 테스트로 재작성 |
| `test_search/test_engine.py` | 새 검색 흐름 테스트로 재작성 |

### 의존성 제거 (pyproject.toml)

- `ollama` — 삭제
- `kuzu` — 삭제

---

## 5. 임베딩 전략

### 기본 모델

- `paraphrase-multilingual-MiniLM-L12-v2` (470MB, 384차원)
- 임베딩 모델은 config 한 줄로 교체 가능하게 추상화

### 향후 테스트 후보

| 모델 | 크기 | 차원 | 한국어 | Matryoshka | Long Context |
|------|------|------|--------|------------|-------------|
| paraphrase-multilingual-MiniLM-L12-v2 | 470MB | 384 | ★★★ | ✗ | 512 |
| jina-embeddings-v3 | ~600MB | 1024 | ★★★★ | ✅ | 8192 |
| KURE (고려대) | ~2GB | 1024 | ★★★★★ | △ | 512 |
| bge-m3 | ~2.2GB | 1024 | ★★★★★ | △ | 8192 |
| EmbeddingGemma | ~600MB | 768 | ★★★ | ✅ | 2048 |

---

## 6. 검색 품질 강화 기법

### Hybrid Search (BM25 + 벡터)

벡터는 "뜻"으로, BM25는 "단어"로 검색하여 결합.

```
"Kuzu DB" 검색 시:
  벡터: 의미적으로 비슷한 청크 (DB, 데이터베이스...)
  BM25: "Kuzu" 단어가 정확히 포함된 청크
  → 결합하면 정확도 향상
```

- ChromaDB의 where 필터 + 별도 BM25 인덱스 병행
- 난이도: 낮음

### Late Chunking (맥락 보존)

일반 청킹은 맥락을 잃음. Late Chunking은 전체 세션을 먼저 인코딩한 뒤 나중에 분리.

```
일반: 청크 분리 → 각각 임베딩 (맥락 손실)
Late: 전체 임베딩 → 나중에 분리 (맥락 보존)
```

- 대명사/참조가 많은 한국어 대화에서 정확도 10~12% 향상
- Long Context 지원 모델 필요 (jina-v3, bge-m3)
- 세션이 8192 토큰 초과 시: 큰 블록으로 1차 분리 → 블록별 Late Chunking 적용
- 난이도: 중간

### Matryoshka + Late Chunking 결합

두 기법은 직교(orthogonal) — 동시 적용 가능:

```
긴 세션 (100턴)
  → 전체 세션을 통째로 임베딩 모델에 입력 (Late Chunking)
  → 모델이 전체 맥락을 보고 토큰별 임베딩 생성
  → 그 후에 청크 단위로 분리 (맥락 보존 ✅)
  → 각 청크 벡터를 1024 → 256으로 축소 (Matryoshka ✅)
  → ChromaDB에 저장
```

- Late Chunking = 임베딩 "품질"을 올리는 기법
- Matryoshka = 임베딩 "크기"를 줄이는 기법
- 조건: 두 가지 모두 지원하는 모델 필요 (jina-embeddings-v3 유력)
- 난이도: 중간

### Binary Quantization (극한 경량화, 선택)

float32 → 1bit 변환. 32배 메모리 절약.

- Matryoshka + Binary 결합 시 최대 256배 경량화, 품질 ~90% 유지
- 난이도: 중간

---

## 7. 구현 순서

### Phase 1: 핵심 전환 (파이프라인 단순화)

| 순서 | 작업 | 파일 |
|------|------|------|
| 1 | models.py 정리 — Triple/Entity 삭제, SessionMeta 추가 | models.py |
| 2 | parser.py — SessionMeta 추출 (cwd, gitBranch, timestamp) | parser.py |
| 3 | chunker.py — SessionMeta를 Chunk에 전파 | chunker.py |
| 4 | vector.py — 청크 원문 + 메타데이터 저장/검색 | vector.py |
| 5 | engine.py — 벡터 검색 → 세션 그루핑 → 청크 반환 | engine.py |
| 6 | config.py — OLLAMA_MODEL, KUZU 설정 제거 | config.py |
| 7 | cli/app.py — 새 파이프라인 반영 | app.py |
| 8 | 불필요 파일 삭제 (6개) | pipeline/, storage/ |
| 9 | 테스트 정리 — 삭제 4개, 수정 3개 | tests/ |
| 10 | pyproject.toml — ollama, kuzu 의존성 제거 | pyproject.toml |

**결과: 동작하는 MVP. Ollama 없이 수 초 내 ingest + 검색.**

### Phase 2: 검색 품질 강화

| 순서 | 작업 | 난이도 |
|------|------|--------|
| 1 | Hybrid Search (BM25 + 벡터) | 낮음 |
| 2 | Late Chunking 적용 | 중간 |
| 3 | Matryoshka 차원 축소 | 낮음 |
| 4 | 임베딩 모델 비교 테스트 | 낮음 |
| 5 | Binary Quantization (선택) | 중간 |

### Phase 3: MCP 서버 통합

| 순서 | 작업 |
|------|------|
| 1 | MCP search_memory tool — cwd 자동 감지 + 프로젝트 필터 |
| 2 | 크로스 프로젝트 검색 — 쿼리에서 프로젝트명 감지 |
| 3 | --all 전체 프로젝트 검색 |

---

## 참고 자료

- [Matryoshka Representation Learning](https://arxiv.org/abs/2205.13147)
- [Quantization Aware Matryoshka Adaptation (CIKM 2025)](https://dl.acm.org/doi/10.1145/3746252.3761077)
- [Binary & Scalar Embedding Quantization (HuggingFace)](https://huggingface.co/blog/embedding-quantization)
- [Late Chunking (Weaviate)](https://weaviate.io/blog/late-chunking)
- [RAG Advanced Retrieval Patterns 2026](https://dev.to/young_gao/rag-is-not-dead-advanced-retrieval-patterns-that-actually-work-in-2026-2gbo)
- [KURE — 한국어 특화 임베딩 모델](https://github.com/nlpai-lab/KURE)
- [Mem0 — AI Memory Layer](https://github.com/mem0ai/mem0)
- [80% Cost Reduction with Quantization + Matryoshka](https://towardsdatascience.com/649627-2/)
