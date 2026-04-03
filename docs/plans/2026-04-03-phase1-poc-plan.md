# Phase 1 PoC Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Claude Code JSONL 대화 로그 1개로 전체 파이프라인을 관통하여, `wwt ingest` → `wwt search`로 과거 대화를 검색할 수 있게 한다.

**Architecture:** 파이프라인 순서(parser → chunker → resolver → extractor → entity → storage)를 따라 바닥부터 구현. 각 단계가 독립적으로 테스트 가능하도록 하고, 마지막에 CLI로 전체를 조합한다.

**Tech Stack:** Python 3.12+, uv, Kuzu, ChromaDB, Ollama (qwen3:4b), sentence-transformers, typer, pydantic, pytest

**Claude Code JSONL 포맷:**
```jsonl
{"type":"permission-mode","permissionMode":"default","sessionId":"..."}
{"type":"user","message":{"role":"user","content":"텍스트" | [{"type":"text","text":"..."},...]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"..."},{"type":"tool_use",...},{"type":"thinking",...}]}}
{"type":"system",...}
```
- `type`이 "user" 또는 "assistant"인 행만 추출
- `content`가 리스트인 경우 `type: "text"` 블록만 추출 (tool_use, thinking, tool_result 제외)

---

## Task 1: Parser — JSONL 파싱

**Files:**
- Modify: `src/whatwasthat/pipeline/parser.py`
- Test: `tests/test_pipeline/test_parser.py`
- Create: `tests/fixtures/sample_session.jsonl` (테스트용 샘플 데이터)

**Step 1: 테스트용 fixture 생성**

`tests/fixtures/sample_session.jsonl`:
```jsonl
{"type":"permission-mode","permissionMode":"default","sessionId":"test-session-001"}
{"type":"system","message":{"role":"system","content":"System prompt..."}}
{"type":"user","message":{"role":"user","content":"FastAPI 대신 Flask 쓰자"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","text":"생각 중..."},{"type":"text","text":"FastAPI가 async 지원이 좋으니 유지하는 게 어떨까요?"}]}}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"그래 FastAPI로 하자"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"좋습니다. FastAPI로 진행하겠습니다."},{"type":"tool_use","id":"tool1","name":"Write","input":{}}]}}
```

**Step 2: 실패하는 테스트 작성**

`tests/test_pipeline/test_parser.py`:
```python
from pathlib import Path
from whatwasthat.pipeline.parser import parse_jsonl
from whatwasthat.models import Turn

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestParseJsonl:
    def test_parse_extracts_user_and_assistant_turns(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        assert len(turns) == 4  # user, assistant, user, assistant (system/permission 제외)
        assert turns[0].role == "user"
        assert turns[0].content == "FastAPI 대신 Flask 쓰자"

    def test_parse_filters_non_text_content(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        # assistant 응답에서 thinking, tool_use 제외하고 text만 추출
        assert "생각 중" not in turns[1].content
        assert "async 지원" in turns[1].content

    def test_parse_handles_list_content(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        # content가 리스트인 user 메시지도 text 추출
        assert turns[2].content == "그래 FastAPI로 하자"

    def test_parse_empty_file(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        turns = parse_jsonl(empty)
        assert turns == []

    def test_parse_returns_session_id(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        # 모든 턴에 session_id 없음 (Turn 모델에 없음) — 파서는 Turn만 반환
        assert all(isinstance(t, Turn) for t in turns)
```

**Step 3: 테스트 실행 (실패 확인)**

Run: `cd /Users/hyuk/PycharmProjects/whatwasthat && uv run pytest tests/test_pipeline/test_parser.py -v`
Expected: FAIL

**Step 4: 구현**

`src/whatwasthat/pipeline/parser.py`:
```python
"""대화 로그 파싱 - JSONL 파일을 Turn 리스트로 변환."""

import json
from pathlib import Path

from whatwasthat.models import Turn

_ALLOWED_TYPES = {"user", "assistant"}


def _extract_text(content: str | list[dict]) -> str:
    """content 필드에서 텍스트만 추출."""
    if isinstance(content, str):
        return content
    text_parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block["text"])
    return "\n".join(text_parts)


def parse_jsonl(file_path: Path) -> list[Turn]:
    """Claude Code JSONL 대화 로그를 파싱하여 Turn 리스트로 변환."""
    turns: list[Turn] = []
    if not file_path.exists() or file_path.stat().st_size == 0:
        return turns

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("type") not in _ALLOWED_TYPES:
                continue
            msg = obj.get("message", {})
            role = msg.get("role", "")
            raw_content = msg.get("content", "")
            text = _extract_text(raw_content)
            if text:
                turns.append(Turn(role=role, content=text))
    return turns


def parse_session_dir(session_dir: Path) -> dict[str, list[Turn]]:
    """디렉토리 내 모든 JSONL 세션 파일을 파싱."""
    results: dict[str, list[Turn]] = {}
    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        session_id = jsonl_file.stem
        results[session_id] = parse_jsonl(jsonl_file)
    return results
```

**Step 5: 테스트 실행 (통과 확인)**

Run: `cd /Users/hyuk/PycharmProjects/whatwasthat && uv run pytest tests/test_pipeline/test_parser.py -v`
Expected: PASS (5 tests)

**Step 6: 커밋**

```bash
git add tests/fixtures/ tests/test_pipeline/test_parser.py src/whatwasthat/pipeline/parser.py
git commit -m "feat(parser): JSONL 대화 로그 파싱 구현"
```

---

## Task 2: Storage/Graph — Kuzu 그래프 DB

**Files:**
- Modify: `src/whatwasthat/storage/graph.py`
- Test: `tests/test_storage/test_graph.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_storage/test_graph.py`:
```python
from whatwasthat.storage.graph import GraphStore
from whatwasthat.models import Triple, Entity


class TestGraphStore:
    def test_initialize_creates_schema(self, tmp_data_dir):
        store = GraphStore(tmp_data_dir / "graph")
        store.initialize()
        # 초기화 후 에러 없이 빈 결과 조회 가능
        assert store.get_session_triples("nonexistent") == []

    def test_add_and_get_triples(self, tmp_data_dir):
        store = GraphStore(tmp_data_dir / "graph")
        store.initialize()
        triples = [
            Triple(
                subject="FastAPI", subject_type="Framework",
                predicate="CHOSEN_OVER", object="Flask",
                object_type="Framework", temporal="decided",
            ),
        ]
        store.add_triples("session-001", triples)
        result = store.get_session_triples("session-001")
        assert len(result) == 1
        assert result[0].subject == "FastAPI"
        assert result[0].predicate == "CHOSEN_OVER"

    def test_find_related_sessions(self, tmp_data_dir):
        store = GraphStore(tmp_data_dir / "graph")
        store.initialize()
        triples = [
            Triple(
                subject="FastAPI", subject_type="Framework",
                predicate="CHOSEN_OVER", object="Flask",
                object_type="Framework", temporal="decided",
            ),
        ]
        store.add_triples("session-001", triples)
        sessions = store.find_related_sessions(["FastAPI"])
        assert len(sessions) >= 1
        assert sessions[0].id == "session-001"

    def test_get_entity_history(self, tmp_data_dir):
        store = GraphStore(tmp_data_dir / "graph")
        store.initialize()
        t1 = Triple(
            subject="MySQL", subject_type="Database",
            predicate="CHOSEN_OVER", object="PostgreSQL",
            object_type="Database", temporal="decided",
        )
        t2 = Triple(
            subject="MySQL", subject_type="Database",
            predicate="CHOSEN_BECAUSE", object="팀 기존 사용",
            object_type="Reason",
        )
        store.add_triples("session-002", [t1, t2])
        history = store.get_entity_history("MySQL")
        assert len(history) == 2
```

**Step 2: 테스트 실행 (실패 확인)**

Run: `uv run pytest tests/test_storage/test_graph.py -v`
Expected: FAIL

**Step 3: 구현**

`src/whatwasthat/storage/graph.py`:
```python
"""Kuzu 그래프 DB 래퍼 - 스키마 초기화, 트리플 CRUD, Cypher 쿼리."""

import uuid
from datetime import datetime
from pathlib import Path

import kuzu

from whatwasthat.models import Entity, Session, Triple


class GraphStore:
    """Kuzu 그래프 DB 래퍼."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: kuzu.Database | None = None
        self._conn: kuzu.Connection | None = None

    def _ensure_connection(self) -> kuzu.Connection:
        if self._conn is None:
            self._db = kuzu.Database(str(self._db_path))
            self._conn = kuzu.Connection(self._db)
        return self._conn

    def initialize(self) -> None:
        """스키마 초기화."""
        conn = self._ensure_connection()
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Entity (
                id STRING, name STRING, type STRING,
                created_at TIMESTAMP DEFAULT timestamp('2024-01-01'),
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Session (
                id STRING, source STRING DEFAULT 'claude-code',
                created_at TIMESTAMP DEFAULT timestamp('2024-01-01'),
                summary STRING DEFAULT '',
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE REL TABLE IF NOT EXISTS RELATION (
                FROM Entity TO Entity,
                type STRING, session_id STRING,
                temporal STRING DEFAULT '',
                confidence DOUBLE DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT timestamp('2024-01-01')
            )
        """)
        conn.execute("""
            CREATE REL TABLE IF NOT EXISTS APPEARS_IN (
                FROM Entity TO Session
            )
        """)

    def _ensure_entity(self, name: str, entity_type: str) -> str:
        """엔티티가 없으면 생성, 있으면 ID 반환."""
        conn = self._ensure_connection()
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.name = $name RETURN e.id",
            parameters={"name": name},
        )
        while result.has_next():
            return result.get_next()[0]
        entity_id = str(uuid.uuid4())[:8]
        conn.execute(
            "CREATE (e:Entity {id: $id, name: $name, type: $type})",
            parameters={"id": entity_id, "name": name, "type": entity_type},
        )
        return entity_id

    def _ensure_session(self, session_id: str) -> None:
        """세션 노드가 없으면 생성."""
        conn = self._ensure_connection()
        result = conn.execute(
            "MATCH (s:Session) WHERE s.id = $id RETURN s.id",
            parameters={"id": session_id},
        )
        if not result.has_next():
            conn.execute(
                "CREATE (s:Session {id: $id})",
                parameters={"id": session_id},
            )

    def add_triples(self, session_id: str, triples: list[Triple]) -> None:
        """세션에 트리플 리스트 저장."""
        conn = self._ensure_connection()
        self._ensure_session(session_id)
        for triple in triples:
            subj_id = self._ensure_entity(triple.subject, triple.subject_type)
            obj_id = self._ensure_entity(triple.object, triple.object_type)
            conn.execute(
                """
                MATCH (s:Entity), (o:Entity)
                WHERE s.id = $sid AND o.id = $oid
                CREATE (s)-[:RELATION {
                    type: $type, session_id: $session_id,
                    temporal: $temporal, confidence: $confidence
                }]->(o)
                """,
                parameters={
                    "sid": subj_id, "oid": obj_id,
                    "type": triple.predicate, "session_id": session_id,
                    "temporal": triple.temporal or "",
                    "confidence": triple.confidence,
                },
            )
            # APPEARS_IN 관계
            for eid in (subj_id, obj_id):
                conn.execute(
                    """
                    MATCH (e:Entity), (sess:Session)
                    WHERE e.id = $eid AND sess.id = $sid
                    MERGE (e)-[:APPEARS_IN]->(sess)
                    """,
                    parameters={"eid": eid, "sid": session_id},
                )

    def get_session_triples(self, session_id: str) -> list[Triple]:
        """세션의 모든 트리플 조회."""
        conn = self._ensure_connection()
        result = conn.execute(
            """
            MATCH (s:Entity)-[r:RELATION]->(o:Entity)
            WHERE r.session_id = $session_id
            RETURN s.name, s.type, r.type, o.name, o.type, r.temporal, r.confidence
            """,
            parameters={"session_id": session_id},
        )
        triples: list[Triple] = []
        while result.has_next():
            row = result.get_next()
            triples.append(Triple(
                subject=row[0], subject_type=row[1],
                predicate=row[2],
                object=row[3], object_type=row[4],
                temporal=row[5] if row[5] else None,
                confidence=row[6],
            ))
        return triples

    def get_entity_history(self, entity_name: str) -> list[Triple]:
        """엔티티의 시간순 변천 이력 조회."""
        conn = self._ensure_connection()
        result = conn.execute(
            """
            MATCH (s:Entity)-[r:RELATION]->(o:Entity)
            WHERE s.name = $name OR o.name = $name
            RETURN s.name, s.type, r.type, o.name, o.type, r.temporal, r.confidence
            """,
            parameters={"name": entity_name},
        )
        triples: list[Triple] = []
        while result.has_next():
            row = result.get_next()
            triples.append(Triple(
                subject=row[0], subject_type=row[1],
                predicate=row[2],
                object=row[3], object_type=row[4],
                temporal=row[5] if row[5] else None,
                confidence=row[6],
            ))
        return triples

    def find_related_sessions(self, entity_names: list[str]) -> list[Session]:
        """엔티티와 관련된 세션 목록 조회."""
        conn = self._ensure_connection()
        sessions: dict[str, Session] = {}
        for name in entity_names:
            result = conn.execute(
                """
                MATCH (e:Entity)-[:APPEARS_IN]->(s:Session)
                WHERE e.name = $name
                RETURN s.id, s.source, s.summary
                """,
                parameters={"name": name},
            )
            while result.has_next():
                row = result.get_next()
                sid = row[0]
                if sid not in sessions:
                    sessions[sid] = Session(
                        id=sid,
                        source=row[1] or "claude-code",
                        created_at=datetime.now(),
                        summary=row[2] or "",
                    )
        return list(sessions.values())
```

**Step 4: 테스트 실행 (통과 확인)**

Run: `uv run pytest tests/test_storage/test_graph.py -v`
Expected: PASS (4 tests)

**Step 5: 커밋**

```bash
git add src/whatwasthat/storage/graph.py tests/test_storage/test_graph.py
git commit -m "feat(storage): Kuzu 그래프 DB 래퍼 구현"
```

---

## Task 3: Storage/Vector — ChromaDB 벡터 검색

**Files:**
- Modify: `src/whatwasthat/storage/vector.py`
- Test: `tests/test_storage/test_vector.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_storage/test_vector.py`:
```python
from whatwasthat.storage.vector import VectorStore
from whatwasthat.models import Entity


class TestVectorStore:
    def test_initialize(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        # 초기화 후 빈 검색 가능
        results = store.search("anything", top_k=5)
        assert results == []

    def test_upsert_and_search(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        entities = [
            Entity(id="e1", name="FastAPI", type="Framework"),
            Entity(id="e2", name="Flask", type="Framework"),
            Entity(id="e3", name="MySQL", type="Database"),
        ]
        store.upsert_entities(entities)
        results = store.search("웹 프레임워크", top_k=2)
        assert len(results) <= 2
        # entity_id, score 튜플
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    def test_search_relevance(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        entities = [
            Entity(id="e1", name="GradientSHAP", type="Technology"),
            Entity(id="e2", name="KernelSHAP", type="Technology"),
            Entity(id="e3", name="PostgreSQL", type="Database"),
        ]
        store.upsert_entities(entities)
        results = store.search("SHAP 분석 기법", top_k=3)
        # SHAP 관련 엔티티가 상위에 올라야 함
        entity_ids = [r[0] for r in results]
        assert "e1" in entity_ids[:2] or "e2" in entity_ids[:2]
```

**Step 2: 테스트 실행 (실패 확인)**

Run: `uv run pytest tests/test_storage/test_vector.py -v`
Expected: FAIL

**Step 3: 구현**

`src/whatwasthat/storage/vector.py`:
```python
"""ChromaDB 벡터 DB 래퍼 - 임베딩, upsert, 시맨틱 검색."""

from pathlib import Path

import chromadb

from whatwasthat.models import Entity


class VectorStore:
    """ChromaDB 벡터 검색 래퍼."""

    COLLECTION_NAME = "wwt_entities"

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None

    def initialize(self) -> None:
        """ChromaDB 컬렉션 초기화."""
        self._db_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._db_path))
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _get_collection(self) -> chromadb.Collection:
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")
        return self._collection

    def upsert_entities(self, entities: list[Entity]) -> None:
        """엔티티 임베딩 저장/갱신."""
        collection = self._get_collection()
        ids = [e.id for e in entities]
        documents = [f"{e.name} - {e.type}" for e in entities]
        metadatas = [{"name": e.name, "type": e.type} for e in entities]
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """시맨틱 검색 - (entity_id, score) 리스트 반환."""
        collection = self._get_collection()
        if collection.count() == 0:
            return []
        actual_k = min(top_k, collection.count())
        results = collection.query(query_texts=[query], n_results=actual_k)
        pairs: list[tuple[str, float]] = []
        if results["ids"] and results["distances"]:
            for entity_id, distance in zip(results["ids"][0], results["distances"][0]):
                score = 1.0 - distance  # cosine distance → similarity
                pairs.append((entity_id, score))
        return pairs
```

**Note:** PoC에서는 ChromaDB 기본 임베딩 모델을 사용. Phase 3에서 sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)로 교체.

**Step 4: 테스트 실행 (통과 확인)**

Run: `uv run pytest tests/test_storage/test_vector.py -v`
Expected: PASS (3 tests)

**Step 5: 커밋**

```bash
git add src/whatwasthat/storage/vector.py tests/test_storage/test_vector.py
git commit -m "feat(storage): ChromaDB 벡터 검색 래퍼 구현"
```

---

## Task 4: Chunker — 주제 기반 청킹

**Files:**
- Modify: `src/whatwasthat/pipeline/chunker.py`
- Test: `tests/test_pipeline/test_chunker.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_pipeline/test_chunker.py`:
```python
import uuid
from whatwasthat.pipeline.chunker import chunk_turns
from whatwasthat.models import Turn, Chunk


def _make_turns(contents: list[tuple[str, str]]) -> list[Turn]:
    return [Turn(role=r, content=c) for r, c in contents]


class TestChunkTurns:
    def test_single_topic_single_chunk(self):
        turns = _make_turns([
            ("user", "FastAPI 대신 Flask 쓰자"),
            ("assistant", "FastAPI가 async 지원이 좋습니다"),
            ("user", "그래 FastAPI로 하자"),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert len(chunks) == 1
        assert len(chunks[0].turns) == 3

    def test_respects_max_turns(self):
        turns = _make_turns([
            ("user", f"메시지 {i}") for i in range(15)
        ])
        chunks = chunk_turns(turns, session_id="s1", max_turns=5)
        assert all(len(c.turns) <= 5 for c in chunks)

    def test_empty_turns(self):
        chunks = chunk_turns([], session_id="s1")
        assert chunks == []

    def test_chunk_has_raw_text(self):
        turns = _make_turns([
            ("user", "DB를 PostgreSQL로 하자"),
            ("assistant", "좋습니다"),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert "PostgreSQL" in chunks[0].raw_text

    def test_chunk_has_session_id(self):
        turns = _make_turns([("user", "테스트")])
        chunks = chunk_turns(turns, session_id="my-session")
        assert chunks[0].session_id == "my-session"
```

**Step 2: 테스트 실행 (실패 확인)**

Run: `uv run pytest tests/test_pipeline/test_chunker.py -v`
Expected: FAIL

**Step 3: 구현**

PoC에서는 단순한 슬라이딩 윈도우 방식으로 구현. 고급 주제 감지는 Phase 3에서.

`src/whatwasthat/pipeline/chunker.py`:
```python
"""주제 기반 청킹 - Turn 리스트를 의미 단위 Chunk로 분리."""

import uuid

from whatwasthat.models import Chunk, Turn


def chunk_turns(
    turns: list[Turn],
    session_id: str,
    min_turns: int = 3,
    max_turns: int = 10,
) -> list[Chunk]:
    """Turn 리스트를 Chunk로 분리.

    PoC: max_turns 기준 슬라이딩 윈도우. 고급 주제 감지는 Phase 3.
    """
    if not turns:
        return []

    chunks: list[Chunk] = []
    for i in range(0, len(turns), max_turns):
        batch = turns[i : i + max_turns]
        raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in batch)
        chunks.append(Chunk(
            id=str(uuid.uuid4())[:8],
            session_id=session_id,
            turns=batch,
            raw_text=raw_text,
        ))
    return chunks
```

**Step 4: 테스트 실행 (통과 확인)**

Run: `uv run pytest tests/test_pipeline/test_chunker.py -v`
Expected: PASS (5 tests)

**Step 5: 커밋**

```bash
git add src/whatwasthat/pipeline/chunker.py tests/test_pipeline/test_chunker.py
git commit -m "feat(chunker): 슬라이딩 윈도우 청킹 구현 (PoC)"
```

---

## Task 5: Extractor — Ollama 트리플 추출

**Files:**
- Modify: `src/whatwasthat/pipeline/extractor.py`
- Test: `tests/test_pipeline/test_extractor.py`
- Create: `src/whatwasthat/pipeline/prompts.py` (추출 프롬프트 템플릿)

**Step 1: 프롬프트 템플릿 생성**

`src/whatwasthat/pipeline/prompts.py`:
```python
"""트리플 추출용 프롬프트 템플릿."""

EXTRACTION_PROMPT = """아래 대화에서 사실, 결정, 관계를 추출하세요.
반드시 JSON으로만 응답하세요. 마크다운 코드블록 없이 순수 JSON만 출력하세요.

{{"triples": [
  {{"s": "주어", "s_type": "타입", "p": "관계", "o": "목적어", "o_type": "타입", "temporal": "decided|rejected|ongoing|null"}}
]}}

### 예시 1
입력: "[user]: FastAPI 대신 Flask 쓰자\\n[assistant]: FastAPI가 async 좋으니 유지하자\\n[user]: 그래 FastAPI로"
출력: {{"triples": [
  {{"s":"FastAPI","s_type":"Framework","p":"CHOSEN_OVER","o":"Flask","o_type":"Framework","temporal":"decided"}},
  {{"s":"FastAPI","s_type":"Framework","p":"HAS_ADVANTAGE","o":"async 지원","o_type":"Feature","temporal":null}}
]}}

### 예시 2
입력: "[user]: 이 에러 뭐 때문이지?\\n[assistant]: pip 버전 문제입니다\\n[user]: 업그레이드하니 해결됐다"
출력: {{"triples": [
  {{"s":"pip 구버전","s_type":"Problem","p":"CAUSED","o":"에러","o_type":"Issue","temporal":null}},
  {{"s":"pip upgrade","s_type":"Solution","p":"SOLVED","o":"에러","o_type":"Issue","temporal":"decided"}}
]}}

### 실제 입력
{chunk_text}
"""
```

**Step 2: 실패하는 테스트 작성**

`tests/test_pipeline/test_extractor.py`:
```python
import json
from unittest.mock import patch, MagicMock
from whatwasthat.pipeline.extractor import extract_triples, parse_llm_response
from whatwasthat.models import Chunk, Turn, Triple


class TestParseLlmResponse:
    """LLM 응답 파싱 테스트 (Ollama 호출 없이)."""

    def test_parse_valid_json(self):
        response = '{"triples": [{"s": "FastAPI", "s_type": "Framework", "p": "CHOSEN_OVER", "o": "Flask", "o_type": "Framework", "temporal": "decided"}]}'
        triples = parse_llm_response(response)
        assert len(triples) == 1
        assert triples[0].subject == "FastAPI"
        assert triples[0].predicate == "CHOSEN_OVER"

    def test_parse_empty_triples(self):
        response = '{"triples": []}'
        triples = parse_llm_response(response)
        assert triples == []

    def test_parse_malformed_json(self):
        response = "이건 JSON이 아닙니다"
        triples = parse_llm_response(response)
        assert triples == []

    def test_parse_json_with_markdown_fence(self):
        response = '```json\n{"triples": [{"s": "A", "s_type": "T", "p": "R", "o": "B", "o_type": "T", "temporal": null}]}\n```'
        triples = parse_llm_response(response)
        assert len(triples) == 1


class TestExtractTriples:
    """Ollama 호출 모킹 테스트."""

    def test_extract_calls_ollama(self):
        chunk = Chunk(
            id="c1", session_id="s1",
            turns=[Turn(role="user", content="FastAPI로 하자")],
            raw_text="[user]: FastAPI로 하자",
        )
        mock_response = MagicMock()
        mock_response.message.content = '{"triples": [{"s": "FastAPI", "s_type": "Framework", "p": "SELECTED", "o": "프로젝트", "o_type": "Project", "temporal": "decided"}]}'

        with patch("whatwasthat.pipeline.extractor.ollama") as mock_ollama:
            mock_ollama.chat.return_value = mock_response
            triples = extract_triples(chunk)
            assert len(triples) == 1
            mock_ollama.chat.assert_called_once()
```

**Step 3: 테스트 실행 (실패 확인)**

Run: `uv run pytest tests/test_pipeline/test_extractor.py -v`
Expected: FAIL

**Step 4: 구현**

`src/whatwasthat/pipeline/extractor.py`:
```python
"""트리플 추출 - Chunk에서 Knowledge Graph 트리플을 추출."""

import json
import re
import logging

import ollama

from whatwasthat.config import OLLAMA_MODEL
from whatwasthat.models import Chunk, Triple
from whatwasthat.pipeline.prompts import EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


def parse_llm_response(response_text: str) -> list[Triple]:
    """LLM 응답 텍스트를 Triple 리스트로 파싱."""
    # 마크다운 코드 펜스 제거
    cleaned = re.sub(r"```(?:json)?\s*", "", response_text).strip()
    cleaned = cleaned.rstrip("`").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM 응답 JSON 파싱 실패: %s", response_text[:200])
        return []

    triples: list[Triple] = []
    for item in data.get("triples", []):
        try:
            triples.append(Triple(
                subject=item["s"],
                subject_type=item["s_type"],
                predicate=item["p"],
                object=item["o"],
                object_type=item["o_type"],
                temporal=item.get("temporal"),
            ))
        except (KeyError, ValueError) as e:
            logger.warning("트리플 파싱 실패: %s — %s", item, e)
    return triples


def extract_triples(chunk: Chunk, model: str = OLLAMA_MODEL) -> list[Triple]:
    """Ollama로 Chunk에서 트리플 추출."""
    prompt = EXTRACTION_PROMPT.format(chunk_text=chunk.raw_text)
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_llm_response(response.message.content)
```

**Step 5: 테스트 실행 (통과 확인)**

Run: `uv run pytest tests/test_pipeline/test_extractor.py -v`
Expected: PASS (5 tests)

**Step 6: 커밋**

```bash
git add src/whatwasthat/pipeline/prompts.py src/whatwasthat/pipeline/extractor.py tests/test_pipeline/test_extractor.py
git commit -m "feat(extractor): Ollama 트리플 추출 구현"
```

---

## Task 6: Resolver — 대명사 해소 (규칙 기반)

**Files:**
- Modify: `src/whatwasthat/pipeline/resolver.py`
- Test: `tests/test_pipeline/test_resolver.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_pipeline/test_resolver.py`:
```python
from whatwasthat.pipeline.resolver import resolve_references
from whatwasthat.models import Chunk, Turn


def _make_chunk(conversations: list[tuple[str, str]]) -> Chunk:
    turns = [Turn(role=r, content=c) for r, c in conversations]
    raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in turns)
    return Chunk(id="c1", session_id="s1", turns=turns, raw_text=raw_text)


class TestResolveReferences:
    def test_no_pronouns_unchanged(self):
        chunk = _make_chunk([
            ("user", "FastAPI를 사용하자"),
            ("assistant", "FastAPI 좋습니다"),
        ])
        resolved = resolve_references(chunk)
        assert resolved.raw_text == chunk.raw_text

    def test_resolve_korean_pronoun_geugeol(self):
        """'그걸로' → 직전 명사구로 치환."""
        chunk = _make_chunk([
            ("user", "FastAPI랑 Flask 중에 뭐가 좋아?"),
            ("assistant", "FastAPI가 async 지원이 좋습니다"),
            ("user", "그걸로 하자"),
        ])
        resolved = resolve_references(chunk)
        assert "FastAPI" in resolved.turns[2].content

    def test_resolve_korean_pronoun_geuge(self):
        """'그게' → 직전 명사구로 치환."""
        chunk = _make_chunk([
            ("assistant", "GradientSHAP을 추천합니다"),
            ("user", "그게 뭐야?"),
        ])
        resolved = resolve_references(chunk)
        assert "GradientSHAP" in resolved.turns[1].content

    def test_raw_text_also_updated(self):
        chunk = _make_chunk([
            ("assistant", "PostgreSQL을 추천합니다"),
            ("user", "그걸로 하자"),
        ])
        resolved = resolve_references(chunk)
        assert "PostgreSQL" in resolved.raw_text
```

**Step 2: 테스트 실행 (실패 확인)**

Run: `uv run pytest tests/test_pipeline/test_resolver.py -v`
Expected: FAIL

**Step 3: 구현**

PoC: 규칙 기반만. 한국어 대명사/지시어 패턴 매칭으로 직전 assistant 응답의 주요 명사구를 치환.

`src/whatwasthat/pipeline/resolver.py`:
```python
"""대명사 해소 - 지시어/대명사를 실제 명칭으로 치환."""

import re

from whatwasthat.models import Chunk, Turn

# 한국어 지시 대명사 패턴
_PRONOUN_PATTERNS = [
    r"그걸로",
    r"그거로",
    r"그걸",
    r"그거",
    r"그게",
    r"그것",
    r"그것으로",
]

# 명사구 추출: 조사 앞의 단어 (한글+영문+숫자)
_NOUN_PATTERN = re.compile(
    r"([\w\-\.]+(?:\s+[\w\-\.]+)?)"  # 1~2 단어
    r"(?:을|를|이|가|은|는|으로|로|에서|에|의|와|과|랑|이랑)"
)


def _extract_last_noun(text: str) -> str | None:
    """텍스트에서 마지막 주요 명사구 추출."""
    matches = _NOUN_PATTERN.findall(text)
    if matches:
        return matches[-1].strip()
    return None


def _find_referent(turns: list[Turn], current_idx: int) -> str | None:
    """현재 턴 이전의 assistant 응답에서 핵심 명사구 찾기."""
    for i in range(current_idx - 1, -1, -1):
        if turns[i].role == "assistant":
            noun = _extract_last_noun(turns[i].content)
            if noun:
                return noun
    return None


def resolve_references(chunk: Chunk) -> Chunk:
    """Chunk 내 대명사/지시어를 실제 명칭으로 치환.

    1차: 규칙 기반 (패턴 매칭)
    2차: LLM 해소 (Phase 3에서 구현)
    """
    new_turns: list[Turn] = []
    changed = False

    for idx, turn in enumerate(chunk.turns):
        content = turn.content
        for pattern in _PRONOUN_PATTERNS:
            if re.search(pattern, content):
                referent = _find_referent(chunk.turns, idx)
                if referent:
                    content = re.sub(pattern, referent, content, count=1)
                    changed = True
                    break  # 한 턴에서 하나만 치환
        new_turns.append(Turn(role=turn.role, content=content, timestamp=turn.timestamp))

    if not changed:
        return chunk

    raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in new_turns)
    return Chunk(
        id=chunk.id,
        session_id=chunk.session_id,
        turns=new_turns,
        raw_text=raw_text,
        timestamp=chunk.timestamp,
    )
```

**Step 4: 테스트 실행 (통과 확인)**

Run: `uv run pytest tests/test_pipeline/test_resolver.py -v`
Expected: PASS (4 tests)

**Step 5: 커밋**

```bash
git add src/whatwasthat/pipeline/resolver.py tests/test_pipeline/test_resolver.py
git commit -m "feat(resolver): 규칙 기반 한국어 대명사 해소 구현"
```

---

## Task 7: Entity Resolution — 엔티티 해소

**Files:**
- Modify: `src/whatwasthat/pipeline/entity.py`
- Test: `tests/test_pipeline/test_entity.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_pipeline/test_entity.py`:
```python
from whatwasthat.pipeline.entity import resolve_entity
from whatwasthat.models import Entity


class TestResolveEntity:
    def test_exact_match(self):
        existing = [
            Entity(id="e1", name="FastAPI", type="Framework"),
        ]
        result = resolve_entity("FastAPI", existing)
        assert result is not None
        assert result.id == "e1"

    def test_normalized_match_case_insensitive(self):
        existing = [
            Entity(id="e1", name="FastAPI", type="Framework"),
        ]
        result = resolve_entity("fastapi", existing)
        assert result is not None
        assert result.id == "e1"

    def test_normalized_match_whitespace(self):
        existing = [
            Entity(id="e1", name="Gradient SHAP", type="Technology"),
        ]
        result = resolve_entity("GradientSHAP", existing)
        assert result is not None
        assert result.id == "e1"

    def test_no_match_returns_none(self):
        existing = [
            Entity(id="e1", name="FastAPI", type="Framework"),
        ]
        result = resolve_entity("PostgreSQL", existing)
        assert result is None

    def test_empty_existing(self):
        result = resolve_entity("FastAPI", [])
        assert result is None
```

**Step 2: 테스트 실행 (실패 확인)**

Run: `uv run pytest tests/test_pipeline/test_entity.py -v`
Expected: FAIL

**Step 3: 구현**

PoC: 정규화 매칭만. 임베딩 유사도/LLM은 Phase 3에서.

`src/whatwasthat/pipeline/entity.py`:
```python
"""엔티티 해소 - 새 엔티티가 기존 노드와 동일한지 판단."""

import re

from whatwasthat.models import Entity


def _normalize(name: str) -> str:
    """엔티티명 정규화: 소문자, 공백/특수문자 제거."""
    return re.sub(r"[\s\-_\.]+", "", name.lower())


def resolve_entity(new_name: str, existing_entities: list[Entity]) -> Entity | None:
    """새 엔티티명이 기존 엔티티와 동일한지 판단.

    PoC: 정규화 매칭만.
    Phase 3: 임베딩 유사도, LLM 폴백 추가.
    """
    normalized_new = _normalize(new_name)

    for entity in existing_entities:
        # 정확 매칭 (정규화)
        if _normalize(entity.name) == normalized_new:
            return entity
        # alias 매칭
        for alias in entity.aliases:
            if _normalize(alias) == normalized_new:
                return entity

    return None
```

**Step 4: 테스트 실행 (통과 확인)**

Run: `uv run pytest tests/test_pipeline/test_entity.py -v`
Expected: PASS (5 tests)

**Step 5: 커밋**

```bash
git add src/whatwasthat/pipeline/entity.py tests/test_pipeline/test_entity.py
git commit -m "feat(entity): 정규화 기반 엔티티 해소 구현"
```

---

## Task 8: Search Engine — 하이브리드 검색

**Files:**
- Modify: `src/whatwasthat/search/engine.py`
- Test: `tests/test_search/test_engine.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_search/test_engine.py`:
```python
from whatwasthat.search.engine import SearchEngine
from whatwasthat.storage.graph import GraphStore
from whatwasthat.storage.vector import VectorStore
from whatwasthat.models import Triple, Entity


class TestSearchEngine:
    def _setup_stores(self, tmp_data_dir):
        graph = GraphStore(tmp_data_dir / "graph")
        vector = VectorStore(tmp_data_dir / "vector")
        graph.initialize()
        vector.initialize()
        return graph, vector

    def test_search_returns_results(self, tmp_data_dir):
        graph, vector = self._setup_stores(tmp_data_dir)
        # 데이터 투입
        triples = [
            Triple(subject="FastAPI", subject_type="Framework",
                   predicate="CHOSEN_OVER", object="Flask",
                   object_type="Framework", temporal="decided"),
        ]
        graph.add_triples("session-001", triples)
        vector.upsert_entities([
            Entity(id="e1", name="FastAPI", type="Framework"),
            Entity(id="e2", name="Flask", type="Framework"),
        ])

        engine = SearchEngine(graph=graph, vector=vector)
        results = engine.search("웹 프레임워크 선택")
        assert len(results) >= 1
        assert results[0].session_id == "session-001"

    def test_search_empty_db(self, tmp_data_dir):
        graph, vector = self._setup_stores(tmp_data_dir)
        engine = SearchEngine(graph=graph, vector=vector)
        results = engine.search("아무거나")
        assert results == []

    def test_search_groups_by_session(self, tmp_data_dir):
        graph, vector = self._setup_stores(tmp_data_dir)
        graph.add_triples("s1", [
            Triple(subject="A", subject_type="T", predicate="R",
                   object="B", object_type="T"),
        ])
        graph.add_triples("s2", [
            Triple(subject="A", subject_type="T", predicate="R2",
                   object="C", object_type="T"),
        ])
        vector.upsert_entities([Entity(id="e1", name="A", type="T")])

        engine = SearchEngine(graph=graph, vector=vector)
        results = engine.search("A")
        session_ids = {r.session_id for r in results}
        assert "s1" in session_ids
        assert "s2" in session_ids
```

**Step 2: 테스트 실행 (실패 확인)**

Run: `uv run pytest tests/test_search/test_engine.py -v`
Expected: FAIL

**Step 3: 구현**

`src/whatwasthat/search/engine.py`:
```python
"""하이브리드 검색 엔진 - ChromaDB 시맨틱 검색 + Kuzu 그래프 확장."""

from whatwasthat.models import SearchResult
from whatwasthat.storage.graph import GraphStore
from whatwasthat.storage.vector import VectorStore


class SearchEngine:
    """벡터 + 그래프 하이브리드 검색."""

    def __init__(self, graph: GraphStore, vector: VectorStore) -> None:
        self._graph = graph
        self._vector = vector

    def search(self, query: str, time_range: str | None = None) -> list[SearchResult]:
        """하이브리드 검색: 벡터 시맨틱 → 그래프 확장 → 세션 그루핑."""
        # 1. 벡터 검색으로 관련 엔티티 찾기
        vector_hits = self._vector.search(query, top_k=10)
        if not vector_hits:
            return []

        # 2. 엔티티명으로 변환 (ChromaDB metadata에서)
        collection = self._vector._get_collection()
        entity_ids = [hit[0] for hit in vector_hits]
        entity_data = collection.get(ids=entity_ids)
        entity_names = [
            meta["name"]
            for meta in (entity_data.get("metadatas") or [])
            if meta
        ]

        if not entity_names:
            return []

        # 3. 그래프에서 관련 세션 찾기
        sessions = self._graph.find_related_sessions(entity_names)
        if not sessions:
            return []

        # 4. 세션별 트리플 수집 + SearchResult 생성
        results: list[SearchResult] = []
        score_map = {hit[0]: hit[1] for hit in vector_hits}

        for session in sessions:
            triples = self._graph.get_session_triples(session.id)
            # 최고 점수 사용
            best_score = max(
                (score_map.get(eid, 0.0) for eid in entity_ids),
                default=0.0,
            )
            summary_parts = [
                f"{t.subject} {t.predicate} {t.object}"
                for t in triples[:3]
            ]
            results.append(SearchResult(
                session_id=session.id,
                triples=triples,
                summary=" | ".join(summary_parts),
                score=max(0.0, min(1.0, best_score)),
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results
```

**Step 4: 테스트 실행 (통과 확인)**

Run: `uv run pytest tests/test_search/test_engine.py -v`
Expected: PASS (3 tests)

**Step 5: 커밋**

```bash
git add src/whatwasthat/search/engine.py tests/test_search/test_engine.py
git commit -m "feat(search): 하이브리드 검색 엔진 구현"
```

---

## Task 9: CLI Integration — 전체 파이프라인 연결

**Files:**
- Modify: `src/whatwasthat/cli/app.py`
- Test: (수동 E2E 테스트)

**Step 1: CLI 구현**

`src/whatwasthat/cli/app.py`:
```python
"""wwt CLI 앱 - typer 기반 명령어 인터페이스."""

from pathlib import Path

import typer

from whatwasthat.config import WwtConfig

app = typer.Typer(
    name="wwt",
    help="whatwasthat - AI 대화 기억 솔루션",
)


def _get_config() -> WwtConfig:
    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


@app.command()
def init() -> None:
    """WWT 초기 설정 (DB 디렉토리 생성)."""
    config = _get_config()
    from whatwasthat.storage.graph import GraphStore
    from whatwasthat.storage.vector import VectorStore

    graph = GraphStore(config.kuzu_path)
    graph.initialize()
    vector = VectorStore(config.chroma_path)
    vector.initialize()
    typer.echo(f"WWT 초기화 완료: {config.home_dir}")


@app.command()
def ingest(path: str = typer.Argument(help="JSONL 파일 또는 디렉토리 경로")) -> None:
    """대화 로그를 Knowledge Graph로 적재."""
    config = _get_config()
    file_path = Path(path).expanduser()

    from whatwasthat.pipeline.parser import parse_jsonl, parse_session_dir
    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.resolver import resolve_references
    from whatwasthat.pipeline.extractor import extract_triples
    from whatwasthat.storage.graph import GraphStore
    from whatwasthat.storage.vector import VectorStore
    from whatwasthat.models import Entity

    graph = GraphStore(config.kuzu_path)
    graph.initialize()
    vector = VectorStore(config.chroma_path)
    vector.initialize()

    # 파싱
    if file_path.is_dir():
        sessions = parse_session_dir(file_path)
    else:
        session_id = file_path.stem
        sessions = {session_id: parse_jsonl(file_path)}

    total_triples = 0
    for session_id, turns in sessions.items():
        if not turns:
            continue
        typer.echo(f"세션 {session_id}: {len(turns)} 턴 처리 중...")

        # 청킹
        chunks = chunk_turns(turns, session_id=session_id)

        for chunk in chunks:
            # 대명사 해소
            resolved = resolve_references(chunk)
            # 트리플 추출
            triples = extract_triples(resolved)
            if not triples:
                continue
            # 그래프 저장
            graph.add_triples(session_id, triples)
            # 벡터 저장 (엔티티)
            entities: list[Entity] = []
            seen: set[str] = set()
            for t in triples:
                for name, etype in [(t.subject, t.subject_type), (t.object, t.object_type)]:
                    if name not in seen:
                        seen.add(name)
                        entities.append(Entity(
                            id=f"{name[:8].lower().replace(' ', '_')}",
                            name=name, type=etype,
                        ))
            vector.upsert_entities(entities)
            total_triples += len(triples)

    typer.echo(f"완료: {len(sessions)} 세션, {total_triples} 트리플 추출")


@app.command()
def search(query: str = typer.Argument(help="검색 쿼리")) -> None:
    """과거 대화에서 관련 기억 검색."""
    config = _get_config()

    from whatwasthat.storage.graph import GraphStore
    from whatwasthat.storage.vector import VectorStore
    from whatwasthat.search.engine import SearchEngine

    graph = GraphStore(config.kuzu_path)
    graph.initialize()
    vector = VectorStore(config.chroma_path)
    vector.initialize()

    engine = SearchEngine(graph=graph, vector=vector)
    results = engine.search(query)

    if not results:
        typer.echo("관련 기억을 찾지 못했습니다.")
        return

    typer.echo(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")
    for i, result in enumerate(results, 1):
        typer.echo(f"  {i}. 세션 {result.session_id} (점수: {result.score:.2f})")
        for triple in result.triples[:5]:
            temporal_tag = f" [{triple.temporal}]" if triple.temporal else ""
            typer.echo(f"     {triple.subject} —[{triple.predicate}]→ {triple.object}{temporal_tag}")
        typer.echo()


@app.command()
def watch() -> None:
    """백그라운드 데몬 - 새 대화 자동 감지 및 추출. (Phase 2)"""
    typer.echo("watch 기능은 Phase 2에서 구현 예정입니다.")
```

**Step 2: 수동 E2E 테스트**

```bash
# 1. 초기화
uv run wwt init

# 2. 실제 세션 적재
uv run wwt ingest ~/.claude/projects/-Users-hyuk-PycharmProjects-TipOfMyTongue/418c7b60-6950-4311-939d-0503ba6f97ab.jsonl

# 3. 검색
uv run wwt search "프레임워크 선택"
uv run wwt search "SHAP"
```

**Step 3: 커밋**

```bash
git add src/whatwasthat/cli/app.py
git commit -m "feat(cli): ingest + search CLI 명령어 구현"
```

---

## Task 10: E2E 테스트 + 품질 확인

**Step 1: 전체 테스트 실행**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: 모든 테스트 PASS

**Step 2: ruff 린트**

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

**Step 3: 실제 데이터 E2E 테스트**

```bash
uv run wwt init
uv run wwt ingest ~/.claude/projects/-Users-hyuk-PycharmProjects-TipOfMyTongue/418c7b60-6950-4311-939d-0503ba6f97ab.jsonl
uv run wwt search "DB 선택"
uv run wwt search "프로젝트 이름"
```

**Step 4: 최종 커밋**

```bash
git add -A
git commit -m "chore: Phase 1 PoC 완성 - 전체 파이프라인 관통 확인"
```

---

## 구현 순서 요약

| Task | 모듈 | 의존성 | 예상 난이도 |
|------|------|--------|------------|
| 1 | parser | 없음 (순수 JSON) | 낮음 |
| 2 | storage/graph | kuzu | 중간 |
| 3 | storage/vector | chromadb | 중간 |
| 4 | chunker | models만 | 낮음 |
| 5 | extractor | ollama | 중간 |
| 6 | resolver | models만 | 낮음 |
| 7 | entity | models만 | 낮음 |
| 8 | search/engine | storage | 중간 |
| 9 | cli/app | 전체 | 높음 (조합) |
| 10 | E2E | 전체 | 검증 |

Task 1~7은 독립적으로 병렬 구현 가능. Task 8은 Task 2+3 필요. Task 9는 전체 필요.
