# 🤔 WWT (whatwasthat)

### *"그그그그 뭐였지?" 를 해결하는 AI 대화 기억 솔루션*

---

## 1. 프로젝트 개요

### 문제

AI와 대화하며 중요한 결정을 내리고, 시행착오를 겪고, 답을 찾는다.
하지만 다음 세션이 시작되면 AI는 아무것도 기억하지 못한다.
사용자는 "그때 그거 뭐였지?" 하고 혀끝에서 맴돌지만 찾을 수 없다.

### 해결

WWT는 LLM과의 모든 대화를 자동으로 Knowledge Graph로 변환하여,
과거의 결정, 시행착오, 맥락을 자연어로 검색할 수 있게 한다.

```
"SHAP 어떤 걸로 했었지?"

→ 2개의 관련 대화를 찾았습니다.
  ① 5/16 — GradientSHAP 선택 (CNN-LSTM에 적합)
  ② 5/12 — KernelSHAP 시도 후 폐기 (성능 이슈)
  
  어느 대화를 말씀하시나요?
```

### 핵심 가치

- **제로 토큰**: 대화 중 추가 비용 없음. 추출은 대화 후 로컬에서 처리
- **완전 로컬**: 데이터가 사용자 머신을 떠나지 않음. 프라이버시 완전 보장
- **설치 2분**: `pip install whatwasthat` + Ollama만 있으면 끝
- **범용**: 코딩, 기획, 리서치 등 어떤 대화든 기억

---

## 2. 타겟 사용자

```
1차: Claude Code / Claude Desktop 사용자 (개발자)
     "지난주에 그 에러 어떻게 해결했더라?"
     "그 라이브러리 왜 안 쓰기로 했지?"

2차: AI 헤비 유저 전반
     "그 논문 제목이 뭐였지?"
     "지난달 회의에서 결정한 방향이 뭐였더라?"
```

---

## 3. 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│                     사용자 로컬 머신                       │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Claude Code / Claude Desktop                      │  │
│  │                                                    │  │
│  │  대화 중: 정상 사용 (추가 토큰 소모 0)                │  │
│  │  검색 시: MCP 도구 호출 → WWT에 질문                │  │
│  └────────┬────────────────────────┬──────────────────┘  │
│       대화 로그 저장            MCP 연결                   │
│           │                      │                       │
│           ▼                      ▼                       │
│  ┌────────────────┐   ┌──────────────────────────┐      │
│  │  🔄 Background  │   │  🔍 WWT MCP Server      │      │
│  │  Extractor      │   │                          │      │
│  │                │   │  search_memory(query)     │      │
│  │  대화 종료 감지  │   │  get_session(id)         │      │
│  │      ↓         │   │  get_history(entity)     │      │
│  │  Ollama        │   └────────────┬─────────────┘      │
│  │  (Qwen3.5 4B)  │                │                     │
│  │      ↓         │                │                     │
│  │  트리플 추출    │                │                     │
│  └────────┬───────┘                │                     │
│           │                        │                     │
│           ▼                        ▼                     │
│  ┌────────────────────────────────────────────────────┐  │
│  │  💾 Storage (~/.wwt/data/)                        │  │
│  │                                                    │  │
│  │  Kuzu (그래프 DB)          ChromaDB (벡터 검색)      │  │
│  │  - 트리플 + 관계 저장      - 시맨틱 검색 인덱스      │  │
│  │  - Cypher 쿼리             - 엔티티 임베딩           │  │
│  │  - 서버 불필요              - 서버 불필요             │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 4. 데이터 흐름

### 4.1 기억하기 (대화 종료 후, 백그라운드)

```
대화 종료 감지 (wwt watch 데몬)
    │
    ▼
① 파싱: 대화 로그에서 role + content 추출
    │
    ▼
② 청킹: 주제 전환 지점에서 분리 (한 청크 = 연속된 주제 3~10턴)
    │
    ▼
③ 해소: 세션 내 대명사/지시어 → 실제 명칭으로 치환
   "그거로 하자" → "GradientSHAP으로 하자"
   (같은 세션 문맥이 있으므로 소형 모델로 고정확도)
    │
    ▼
④ 추출: Ollama (Qwen3.5 4B) + few-shot 프롬프트 → JSON 트리플
   {"s": "GradientSHAP", "p": "CHOSEN_OVER", "o": "KernelSHAP"}
    │
    ▼
⑤ 해소: 새 엔티티가 기존 노드와 동일한지 판단
   1차: 정규화 매칭  →  2차: 임베딩 유사도  →  3차: LLM (최후수단)
    │
    ▼
⑥ 저장: Kuzu (그래프) + ChromaDB (벡터)
   모든 엣지에 session_id, valid_from, valid_until 부착
```

### 4.2 떠올리기 (대화 중, MCP 호출)

```
사용자: "그때 DB 뭘로 하기로 했지?"
    │
    ▼
Claude → search_memory("DB 선택") MCP 호출
    │
    ▼
① ChromaDB 시맨틱 검색 → 관련 엔티티 후보
② Kuzu 그래프 순회 → 연결된 서브그래프 확장
③ session_id별 그루핑
    │
    ▼
④ 분기
   ├── 세션 1개 매칭 → 바로 반환
   └── 세션 여러 개 → 선택지 제공
       "어느 대화를 말씀하시나요?"
        ① 5/16 — MySQL 선택 (팀 호환성)
        ② 5/10 — SQLite vs PostgreSQL 비교 (미확정)
    │
    ▼
⑤ 선택된 세션의 서브그래프 + 원본 텍스트 반환
   → Claude가 컨텍스트로 활용하여 응답
```

---

## 5. 세션 ID 기반 기억 선택

WWT의 핵심 UX 패턴.

**세션 내** 모호성은 LLM이 해소한다. 같은 대화 안에서 "그거"가 뭔지는 앞뒤 맥락으로 파악 가능.

**세션 간** 모호성은 사용자가 선택한다. LLM이 추측하는 것보다 정확하고, 비용은 0.

```
[추출 시]
세션 abc123: (GradientSHAP)-[CHOSEN_OVER]->(KernelSHAP) {date: 5/16}
세션 def456: (KernelSHAP)-[ATTEMPTED]->(SHAP분석)       {date: 5/12}
세션 def456: (KernelSHAP)-[REJECTED]->(SHAP분석)        {date: 5/12}

[검색 시]
사용자: "SHAP 어떤 걸로 했었지?"
  → 세션 2개 매칭
  → "어느 대화를 말씀하시나요?"
     ① 5/16 — GradientSHAP 선택
     ② 5/12 — KernelSHAP 시도 후 폐기
```

---

## 6. 스토리지 스키마

### 6.1 Kuzu 그래프

```cypher
-- 노드
CREATE NODE TABLE Entity (
    id STRING, name STRING, type STRING,
    aliases STRING[], created_at TIMESTAMP, updated_at TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE NODE TABLE Session (
    id STRING, source STRING, created_at TIMESTAMP, summary STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE Chunk (
    id STRING, session_id STRING, raw_text STRING, timestamp TIMESTAMP,
    PRIMARY KEY (id)
);

-- 엣지
CREATE REL TABLE RELATION (
    FROM Entity TO Entity,
    type STRING, session_id STRING, chunk_id STRING,
    valid_from TIMESTAMP, valid_until TIMESTAMP,
    confidence DOUBLE, created_at TIMESTAMP
);

CREATE REL TABLE CONTAINS (FROM Session TO Chunk);
CREATE REL TABLE MENTIONS (FROM Chunk TO Entity);
```

### 6.2 ChromaDB

```python
# 엔티티 임베딩 컬렉션
collection = chroma.get_or_create_collection("wwt_entities")

collection.add(
    ids=["entity_uuid"],
    embeddings=[embedding_vector],
    metadatas=[{"name": "GradientSHAP", "type": "Technology"}],
    documents=["GradientSHAP - CNN-LSTM용 SHAP 분석 기법"]
)
```

---

## 7. 추출 프롬프트

파인튜닝 없이 few-shot 프롬프트 엔지니어링으로 동작.

```
아래 대화에서 사실, 결정, 관계를 추출하세요.
반드시 JSON으로만 응답하세요.

{"triples": [
  {"s": "주어", "s_type": "타입", "p": "관계",
   "o": "목적어", "o_type": "타입", "temporal": "decided|rejected|ongoing|null"}
]}

### 예시 1
입력: "FastAPI 대신 Flask 쓰자" → "FastAPI가 async 좋으니 유지하자" → "그래 FastAPI로"
출력: {"triples": [
  {"s":"FastAPI","s_type":"Framework","p":"CHOSEN_OVER","o":"Flask","o_type":"Framework","temporal":"decided"},
  {"s":"FastAPI","s_type":"Framework","p":"HAS_ADVANTAGE","o":"async 지원","o_type":"Feature","temporal":null}
]}

### 예시 2
입력: "이 에러 뭐 때문이지?" → "pip 버전 문제입니다" → "업그레이드하니 해결됐다"
출력: {"triples": [
  {"s":"pip 구버전","s_type":"Problem","p":"CAUSED","o":"에러","o_type":"Issue","temporal":null},
  {"s":"pip upgrade","s_type":"Solution","p":"SOLVED","o":"에러","o_type":"Issue","temporal":"decided"}
]}

### 예시 3
입력: "DB를 PostgreSQL이랑 MySQL 중 뭐로?" → "JSON 필요하면 PostgreSQL" → "팀이 MySQL 써서 그걸로"
출력: {"triples": [
  {"s":"MySQL","s_type":"Database","p":"CHOSEN_OVER","o":"PostgreSQL","o_type":"Database","temporal":"decided"},
  {"s":"MySQL","s_type":"Database","p":"CHOSEN_BECAUSE","o":"팀 기존 사용","o_type":"Reason","temporal":null},
  {"s":"PostgreSQL","s_type":"Database","p":"HAS_ADVANTAGE","o":"JSON 지원","o_type":"Feature","temporal":null}
]}

### 실제 입력
{대화 청크}
```

---

## 8. MCP 인터페이스

### 도구 정의

```python
@tool
def search_memory(query: str, time_range: str = None) -> dict:
    """과거 대화에서 관련 기억을 검색.
    ChromaDB 시맨틱 검색 + Kuzu 그래프 순회.
    결과를 session_id별로 그루핑하여 선택지 제공."""

@tool
def get_session(session_id: str, topic: str = None) -> dict:
    """특정 세션의 관련 서브그래프 + 원본 텍스트 반환.
    search_memory에서 세션 선택 후 호출."""

@tool
def get_history(entity_name: str) -> dict:
    """엔티티의 시간순 변천 이력 반환.
    valid_from/valid_until로 현재 유효 vs 과거 무효 구분."""
```

### Claude Code / Desktop 설정

```json
{
  "mcpServers": {
    "wwt": {
      "command": "wwt",
      "args": ["mcp-server"],
      "env": {}
    }
  }
}
```

---

## 9. 설치 및 사용

### 설치

```bash
# 사전 요구: Python 3.12+, Ollama

pip install whatwasthat
wwt init          # Qwen3.5 4B 다운로드 + DB 초기화 (최초 1회)
```

### 사용

```bash
wwt ingest ~/.claude/     # 과거 대화 일괄 적재
wwt watch                 # 백그라운드 데몬 (새 대화 자동 감지 + 추출)
wwt search "그때 그거"     # CLI 검색
wwt mcp-server            # MCP 서버 시작
```

### 설치 용량

```
Qwen3.5 4B Q4 (Ollama)   ~2.5GB
임베딩 모델                ~120MB
WWT + 의존성               ~130MB
────────────────────────
합계: ~2.8GB (초기 1회 다운로드)

런타임: RAM ~4GB (추출 시만), GPU 불필요 (CPU 백그라운드)
```

---

## 10. 기술 스택

```
추출 LLM:    Qwen3.5 4B Q4 via Ollama (로컬, 크로스 플랫폼)
임베딩:      paraphrase-multilingual-MiniLM-L12-v2 (로컬, 다국어)
그래프 DB:   Kuzu (임베디드, 서버 불필요)
벡터 검색:   ChromaDB (임베디드, 서버 불필요)
MCP 서버:    Python (MCP SDK)
CLI:         Python (typer)
패키지:      uv (Python 3.12+)
```

---

## 11. 로드맵

```
Phase 1 — PoC
  대화 로그 1개로 전체 파이프라인 관통
  파싱 → 추출 → 저장 → CLI 검색 확인
  추출 품질 평가 + 프롬프트 튜닝

Phase 2 — MCP 연동
  MCP 서버 구현 + Claude Code/Desktop 실사용
  세션 ID 기반 선택지 UX 검증
  wwt watch 백그라운드 데몬 구현

Phase 3 — 안정화
  엔티티 해소 정확도 개선
  temporal 무효화 로직 고도화
  다양한 대화 패턴 테스트 (코딩, 기획, 리서치 등)
  에러 핸들링 + 로깅

Phase 4 — 배포
  PyPI 패키지 배포 (pip install whatwasthat)
  wwt init 원커맨드 자동 설정
  Docker Compose 옵션 (서버 배포용)
  문서화 + 사이트

Phase 5 — 확장
  프롬프트 한계 도달 시 Qwen LoRA 파인튜닝
  웹 UI (Vue.js PWA) → 모바일 브라우저
  Capacitor → 네이티브 앱
  다국어 지원 확대
```

---

## 12. 레퍼런스

| 프로젝트 | 참고 포인트 |
|---------|-----------|
| [Graphiti (Zep)](https://github.com/getzep/graphiti) | temporal KG 모델, hybrid search, bi-temporal 설계 |
| [CatchMe (HKUDS)](https://github.com/HKUDS/CatchMe) | Claude Code 스킬 통합, Light/Full 모드 UX |
| [Kuzu](https://github.com/kuzudb/kuzu) | 임베디드 그래프 DB, Cypher 호환 |
| [ChromaDB](https://github.com/chroma-core/chroma) | 임베디드 벡터 DB |

---

> *"그그그그 뭐였지? WWT가 찾아드립니다."*
