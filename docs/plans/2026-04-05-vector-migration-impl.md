# Vector Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Triple 추출 파이프라인을 제거하고, 청크 원문을 직접 벡터화하여 검색하는 구조로 전환

**Architecture:** JSONL → Parser(메타데이터 추출) → Chunker(메타데이터 전파) → VectorStore(청크 원문 + 메타데이터). Ollama/Kuzu 의존성 완전 제거. 검색은 ChromaDB 시맨틱 검색 → 세션별 그루핑.

**Tech Stack:** ChromaDB, sentence-transformers, Pydantic, typer, pytest

**Design doc:** `docs/plans/2026-04-05-vector-migration-design.md`

---

### Task 1: models.py 정리 — Triple/Entity 삭제, SessionMeta 추가

**Files:**
- Modify: `src/whatwasthat/models.py`
- Test: `tests/test_models.py` (새 파일)

**Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import datetime
from whatwasthat.models import Chunk, SessionMeta, SearchResult


class TestSessionMeta:
    def test_create_session_meta(self):
        meta = SessionMeta(
            session_id="abc-123",
            project="whatwasthat",
            project_path="/Users/hyuk/PycharmProjects/whatwasthat",
            git_branch="main",
            started_at=datetime(2026, 4, 5),
        )
        assert meta.session_id == "abc-123"
        assert meta.project == "whatwasthat"
        assert meta.git_branch == "main"
        assert meta.turn_count == 0


class TestChunkMetadata:
    def test_chunk_has_metadata_fields(self):
        chunk = Chunk(
            id="ch1",
            session_id="s1",
            turns=[],
            raw_text="test text",
            project="myproject",
            project_path="/path/to/project",
            git_branch="feature/x",
        )
        assert chunk.project == "myproject"
        assert chunk.git_branch == "feature/x"


class TestSearchResultChunks:
    def test_search_result_has_chunks(self):
        result = SearchResult(
            session_id="s1",
            chunks=[],
            summary="test",
            score=0.8,
            project="myproject",
            git_branch="main",
        )
        assert result.chunks == []
        assert result.project == "myproject"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL (SessionMeta not defined, Chunk missing project field, SearchResult has triples not chunks)

**Step 3: Write minimal implementation**

Replace `src/whatwasthat/models.py` with:

```python
"""WWT 공통 데이터 모델."""

from datetime import datetime

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """대화 한 턴."""

    role: str
    content: str
    timestamp: datetime | None = None


class Chunk(BaseModel):
    """주제 단위 대화 청크."""

    id: str
    session_id: str
    turns: list[Turn]
    raw_text: str
    project: str = ""
    project_path: str = ""
    git_branch: str = ""
    timestamp: datetime | None = None


class SessionMeta(BaseModel):
    """JSONL에서 파싱한 세션 메타데이터."""

    session_id: str
    project: str
    project_path: str
    git_branch: str
    started_at: datetime
    turn_count: int = 0


class SearchResult(BaseModel):
    """검색 결과."""

    session_id: str
    chunks: list[Chunk]
    summary: str
    score: float = Field(ge=0.0, le=1.0)
    project: str = ""
    git_branch: str = ""
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add tests/test_models.py src/whatwasthat/models.py
git commit -m "refactor(models): Triple/Entity 삭제, SessionMeta 추가, SearchResult 청크 기반으로 변경"
```

---

### Task 2: parser.py — SessionMeta 추출 추가

**Files:**
- Modify: `src/whatwasthat/pipeline/parser.py`
- Modify: `tests/test_pipeline/test_parser.py`
- Modify: `tests/fixtures/sample_session.jsonl`

**Step 1: Write the failing test**

`tests/test_pipeline/test_parser.py`에 추가:

```python
from whatwasthat.pipeline.parser import parse_jsonl, parse_session_meta


class TestParseSessionMeta:
    def test_extracts_session_meta(self):
        meta = parse_session_meta(FIXTURES / "sample_session.jsonl")
        assert meta is not None
        assert meta.session_id == "test-session-001"
        assert meta.project_path == "/Users/hyuk/PycharmProjects/TestProject"
        assert meta.project == "TestProject"
        assert meta.git_branch == "main"
        assert meta.started_at is not None

    def test_meta_from_empty_file(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        meta = parse_session_meta(empty)
        assert meta is None
```

`tests/fixtures/sample_session.jsonl`에 메타데이터 필드 추가 (기존 라인 수정):

```jsonl
{"type":"permission-mode","permissionMode":"default","sessionId":"test-session-001"}
{"type":"system","message":{"role":"system","content":"System prompt..."},"cwd":"/Users/hyuk/PycharmProjects/TestProject","sessionId":"test-session-001","gitBranch":"main","timestamp":"2026-04-03T00:06:08.772Z"}
{"type":"user","message":{"role":"user","content":"FastAPI 대신 Flask 쓰자"},"cwd":"/Users/hyuk/PycharmProjects/TestProject","sessionId":"test-session-001","gitBranch":"main","timestamp":"2026-04-03T00:06:10.000Z"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","text":"생각 중..."},{"type":"text","text":"FastAPI가 async 지원이 좋으니 유지하는 게 어떨까요?"}]},"cwd":"/Users/hyuk/PycharmProjects/TestProject","sessionId":"test-session-001","gitBranch":"main","timestamp":"2026-04-03T00:06:15.000Z"}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"그래 FastAPI로 하자"}]},"cwd":"/Users/hyuk/PycharmProjects/TestProject","sessionId":"test-session-001","gitBranch":"main","timestamp":"2026-04-03T00:06:20.000Z"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"좋습니다. FastAPI로 진행하겠습니다."},{"type":"tool_use","id":"tool1","name":"Write","input":{}}]},"cwd":"/Users/hyuk/PycharmProjects/TestProject","sessionId":"test-session-001","gitBranch":"main","timestamp":"2026-04-03T00:06:25.000Z"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline/test_parser.py::TestParseSessionMeta -v`
Expected: FAIL (parse_session_meta not defined)

**Step 3: Write minimal implementation**

`src/whatwasthat/pipeline/parser.py` 하단에 추가:

```python
from whatwasthat.models import SessionMeta


def parse_session_meta(file_path: Path) -> SessionMeta | None:
    """JSONL 파일에서 세션 메타데이터 추출."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return None

    session_id = ""
    cwd = ""
    git_branch = ""
    timestamp_str = ""

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            # 첫 번째로 발견되는 메타데이터 사용
            if not session_id and obj.get("sessionId"):
                session_id = obj["sessionId"]
            if not cwd and obj.get("cwd"):
                cwd = obj["cwd"]
            if not git_branch and obj.get("gitBranch"):
                git_branch = obj["gitBranch"]
            if not timestamp_str and obj.get("timestamp"):
                timestamp_str = obj["timestamp"]
            # 모든 필드를 찾으면 조기 종료
            if session_id and cwd and git_branch and timestamp_str:
                break

    if not session_id:
        return None

    from datetime import datetime

    project_path = cwd
    project = cwd.rstrip("/").split("/")[-1] if cwd else ""
    started_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")) if timestamp_str else datetime.now()

    return SessionMeta(
        session_id=session_id,
        project=project,
        project_path=project_path,
        git_branch=git_branch,
        started_at=started_at,
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline/test_parser.py -v`
Expected: PASS (all parser tests including new meta tests)

**Step 5: Commit**

```bash
git add src/whatwasthat/pipeline/parser.py tests/test_pipeline/test_parser.py tests/fixtures/sample_session.jsonl
git commit -m "feat(parser): SessionMeta 추출 — cwd, gitBranch, timestamp 파싱"
```

---

### Task 3: chunker.py — SessionMeta를 Chunk에 전파

**Files:**
- Modify: `src/whatwasthat/pipeline/chunker.py`
- Modify: `tests/test_pipeline/test_chunker.py`

**Step 1: Write the failing test**

`tests/test_pipeline/test_chunker.py`에 추가:

```python
from datetime import datetime
from whatwasthat.models import SessionMeta


class TestChunkMetadata:
    def test_chunk_receives_session_meta(self):
        meta = SessionMeta(
            session_id="s1",
            project="myproject",
            project_path="/path/to/myproject",
            git_branch="feature/x",
            started_at=datetime(2026, 4, 5),
        )
        turns = _make_turns([
            ("user", _LONG_USER),
            ("assistant", _LONG_ASST),
            ("user", "그래 그렇게 하자. 모델은 Qwen 3.5 4B로 가자."),
        ])
        chunks = chunk_turns(turns, session_id="s1", meta=meta)
        assert chunks[0].project == "myproject"
        assert chunks[0].project_path == "/path/to/myproject"
        assert chunks[0].git_branch == "feature/x"

    def test_chunk_works_without_meta(self):
        turns = _make_turns([
            ("user", _LONG_USER),
            ("assistant", _LONG_ASST),
            ("user", "그래 그렇게 하자. 모델은 Qwen 3.5 4B로 가자."),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert chunks[0].project == ""
        assert chunks[0].git_branch == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline/test_chunker.py::TestChunkMetadata -v`
Expected: FAIL (unexpected keyword argument 'meta')

**Step 3: Write minimal implementation**

`src/whatwasthat/pipeline/chunker.py` 수정:

```python
"""주제 기반 청킹 - Turn 리스트를 의미 단위 Chunk로 분리."""

import uuid

from whatwasthat.models import Chunk, SessionMeta, Turn

_MIN_CHUNK_CHARS = 200


def chunk_turns(
    turns: list[Turn],
    session_id: str,
    min_turns: int = 3,
    max_turns: int = 6,
    meta: SessionMeta | None = None,
) -> list[Chunk]:
    """Turn 리스트를 Chunk로 분리."""
    if not turns:
        return []

    chunks: list[Chunk] = []
    for i in range(0, len(turns), max_turns):
        batch = turns[i : i + max_turns]
        raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in batch)
        has_user = any(t.role == "user" for t in batch)
        if not has_user or len(raw_text) < _MIN_CHUNK_CHARS:
            continue
        chunks.append(Chunk(
            id=str(uuid.uuid4())[:8],
            session_id=session_id,
            turns=batch,
            raw_text=raw_text,
            project=meta.project if meta else "",
            project_path=meta.project_path if meta else "",
            git_branch=meta.git_branch if meta else "",
        ))
    return chunks
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline/test_chunker.py -v`
Expected: PASS (all chunker tests)

**Step 5: Commit**

```bash
git add src/whatwasthat/pipeline/chunker.py tests/test_pipeline/test_chunker.py
git commit -m "feat(chunker): SessionMeta → Chunk 메타데이터 전파"
```

---

### Task 4: vector.py — 청크 원문 + 메타데이터 저장으로 전환

**Files:**
- Modify: `src/whatwasthat/storage/vector.py`
- Modify: `tests/test_storage/test_vector.py`

**Step 1: Write the failing test**

`tests/test_storage/test_vector.py` 전체 교체:

```python
from whatwasthat.models import Chunk, Turn
from whatwasthat.storage.vector import VectorStore


class TestVectorStore:
    def test_initialize(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        assert store._collection is not None

    def test_upsert_chunks(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(
                id="ch1",
                session_id="s1",
                turns=[Turn(role="user", content="DB는 Kuzu로 하자")],
                raw_text="[user]: DB는 Kuzu로 하자",
                project="myproject",
                git_branch="main",
            ),
        ]
        store.upsert_chunks(chunks)
        col = store._get_collection()
        assert col.count() == 1

    def test_search_returns_relevant_chunks(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(
                id="ch1",
                session_id="s1",
                turns=[Turn(role="user", content="DB는 Kuzu를 선택했어")],
                raw_text="[user]: DB는 Kuzu를 선택했어",
                project="myproject",
                git_branch="main",
            ),
            Chunk(
                id="ch2",
                session_id="s1",
                turns=[Turn(role="user", content="프론트엔드는 React로 가자")],
                raw_text="[user]: 프론트엔드는 React로 가자",
                project="myproject",
                git_branch="main",
            ),
        ]
        store.upsert_chunks(chunks)
        results = store.search("데이터베이스 선택", top_k=2)
        assert len(results) > 0
        assert results[0][0] in ("ch1", "ch2")

    def test_search_with_project_filter(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(
                id="ch1", session_id="s1", turns=[], project="projectA",
                raw_text="DB는 Kuzu를 선택", git_branch="main",
            ),
            Chunk(
                id="ch2", session_id="s2", turns=[], project="projectB",
                raw_text="DB는 PostgreSQL 선택", git_branch="main",
            ),
        ]
        store.upsert_chunks(chunks)
        results = store.search("DB 선택", top_k=5, project="projectA")
        assert all(r[0] == "ch1" for r in results)

    def test_search_empty_store(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        results = store.search("아무거나")
        assert results == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_storage/test_vector.py -v`
Expected: FAIL (upsert_chunks not defined)

**Step 3: Write minimal implementation**

`src/whatwasthat/storage/vector.py` 전체 교체:

```python
"""ChromaDB 벡터 DB 래퍼 - 청크 원문 임베딩, 시맨틱 검색."""

from pathlib import Path

import chromadb

from whatwasthat.models import Chunk


class VectorStore:
    """ChromaDB 청크 벡터 검색."""

    COLLECTION_NAME = "wwt_chunks"

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

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """청크 원문 + 메타데이터 저장."""
        if not chunks:
            return
        collection = self._get_collection()
        ids = [c.id for c in chunks]
        documents = [c.raw_text for c in chunks]
        metadatas = [
            {
                "session_id": c.session_id,
                "project": c.project,
                "project_path": c.project_path,
                "git_branch": c.git_branch,
                "chunk_index": i,
                "turn_count": len(c.turns),
            }
            for i, c in enumerate(chunks)
        ]
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def search(
        self,
        query: str,
        top_k: int = 10,
        project: str | None = None,
    ) -> list[tuple[str, float, dict]]:
        """시맨틱 검색 — (chunk_id, score, metadata) 리스트 반환."""
        collection = self._get_collection()
        if collection.count() == 0:
            return []
        actual_k = min(top_k, collection.count())
        where = {"project": project} if project else None
        results = collection.query(
            query_texts=[query],
            n_results=actual_k,
            where=where,
            include=["metadatas", "documents", "distances"],
        )
        pairs: list[tuple[str, float, dict]] = []
        if results["ids"] and results["distances"]:
            for chunk_id, distance, meta in zip(
                results["ids"][0],
                results["distances"][0],
                results["metadatas"][0],
            ):
                score = max(0.0, 1.0 - distance)
                pairs.append((chunk_id, score, meta))
        return pairs
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_storage/test_vector.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add src/whatwasthat/storage/vector.py tests/test_storage/test_vector.py
git commit -m "refactor(vector): 엔티티 → 청크 원문 벡터화 전환, 프로젝트 필터 지원"
```

---

### Task 5: engine.py — 벡터 검색 → 세션 그루핑 → 청크 반환

**Files:**
- Modify: `src/whatwasthat/search/engine.py`
- Modify: `tests/test_search/test_engine.py`

**Step 1: Write the failing test**

`tests/test_search/test_engine.py` 전체 교체:

```python
from whatwasthat.models import Chunk, Turn
from whatwasthat.search.engine import SearchEngine
from whatwasthat.storage.vector import VectorStore


class TestSearchEngine:
    def _make_engine(self, tmp_data_dir):
        vector = VectorStore(tmp_data_dir / "vector")
        vector.initialize()
        return SearchEngine(vector=vector), vector

    def test_search_returns_results(self, tmp_data_dir):
        engine, vector = self._make_engine(tmp_data_dir)
        chunks = [
            Chunk(
                id="ch1", session_id="s1",
                turns=[Turn(role="user", content="DB는 Kuzu로 선택했어")],
                raw_text="[user]: DB는 Kuzu로 선택했어",
                project="myproject", git_branch="main",
            ),
        ]
        vector.upsert_chunks(chunks)
        results = engine.search("데이터베이스")
        assert len(results) > 0
        assert results[0].session_id == "s1"
        assert results[0].project == "myproject"

    def test_search_groups_by_session(self, tmp_data_dir):
        engine, vector = self._make_engine(tmp_data_dir)
        chunks = [
            Chunk(
                id="ch1", session_id="s1",
                turns=[Turn(role="user", content="DB는 Kuzu로")],
                raw_text="[user]: DB는 Kuzu로",
                project="proj", git_branch="main",
            ),
            Chunk(
                id="ch2", session_id="s1",
                turns=[Turn(role="user", content="벡터는 ChromaDB로")],
                raw_text="[user]: 벡터는 ChromaDB로",
                project="proj", git_branch="main",
            ),
            Chunk(
                id="ch3", session_id="s2",
                turns=[Turn(role="user", content="프론트는 React로")],
                raw_text="[user]: 프론트는 React로",
                project="proj", git_branch="dev",
            ),
        ]
        vector.upsert_chunks(chunks)
        results = engine.search("DB 선택")
        session_ids = [r.session_id for r in results]
        # 세션별 그루핑 확인 (중복 세션 없음)
        assert len(session_ids) == len(set(session_ids))

    def test_search_empty_db(self, tmp_data_dir):
        engine, _ = self._make_engine(tmp_data_dir)
        results = engine.search("아무거나")
        assert results == []

    def test_search_with_project_filter(self, tmp_data_dir):
        engine, vector = self._make_engine(tmp_data_dir)
        chunks = [
            Chunk(
                id="ch1", session_id="s1",
                turns=[Turn(role="user", content="DB는 Kuzu로")],
                raw_text="[user]: DB는 Kuzu로",
                project="projectA", git_branch="main",
            ),
            Chunk(
                id="ch2", session_id="s2",
                turns=[Turn(role="user", content="DB는 PostgreSQL로")],
                raw_text="[user]: DB는 PostgreSQL로",
                project="projectB", git_branch="main",
            ),
        ]
        vector.upsert_chunks(chunks)
        results = engine.search("DB", project="projectA")
        assert all(r.project == "projectA" for r in results)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_search/test_engine.py -v`
Expected: FAIL (SearchEngine constructor changed)

**Step 3: Write minimal implementation**

`src/whatwasthat/search/engine.py` 전체 교체:

```python
"""시맨틱 검색 엔진 - ChromaDB 벡터 검색 + 세션 그루핑."""

from collections import defaultdict

from whatwasthat.models import Chunk, SearchResult
from whatwasthat.storage.vector import VectorStore


class SearchEngine:
    """벡터 시맨틱 검색 + 세션 그루핑."""

    def __init__(self, vector: VectorStore) -> None:
        self._vector = vector

    def search(
        self,
        query: str,
        project: str | None = None,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """시맨틱 검색: 벡터 유사도 → 세션별 그루핑."""
        hits = self._vector.search(query, top_k=top_k, project=project)
        if not hits:
            return []

        # chunk_id로 원문 조회
        collection = self._vector._get_collection()
        chunk_ids = [h[0] for h in hits]
        chunk_data = collection.get(ids=chunk_ids, include=["documents", "metadatas"])

        # 세션별 그루핑
        session_chunks: defaultdict[str, list[tuple[Chunk, float]]] = defaultdict(list)
        for i, (chunk_id, score, _) in enumerate(hits):
            meta = chunk_data["metadatas"][i] if chunk_data["metadatas"] else {}
            doc = chunk_data["documents"][i] if chunk_data["documents"] else ""
            chunk = Chunk(
                id=chunk_id,
                session_id=meta.get("session_id", ""),
                turns=[],
                raw_text=doc,
                project=meta.get("project", ""),
                project_path=meta.get("project_path", ""),
                git_branch=meta.get("git_branch", ""),
            )
            session_chunks[chunk.session_id].append((chunk, score))

        # SearchResult 생성
        results: list[SearchResult] = []
        for session_id, chunk_scores in session_chunks.items():
            chunk_scores.sort(key=lambda x: x[1], reverse=True)
            chunks = [c for c, _ in chunk_scores]
            best_score = chunk_scores[0][1]
            first_chunk = chunks[0]
            summary = chunks[0].raw_text[:200]
            results.append(SearchResult(
                session_id=session_id,
                chunks=chunks,
                summary=summary,
                score=best_score,
                project=first_chunk.project,
                git_branch=first_chunk.git_branch,
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_search/test_engine.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/whatwasthat/search/engine.py tests/test_search/test_engine.py
git commit -m "refactor(engine): 그래프 제거, 벡터 → 세션 그루핑 → 청크 반환"
```

---

### Task 6: config.py — Ollama/Kuzu 설정 제거

**Files:**
- Modify: `src/whatwasthat/config.py`

**Step 1: Write minimal implementation**

```python
"""WWT 설정 - 경로, 임베딩 설정, 상수."""

from pathlib import Path

from pydantic import BaseModel

WWT_HOME = Path.home() / ".wwt"
WWT_DATA_DIR = WWT_HOME / "data"
CHROMA_DB_PATH = WWT_DATA_DIR / "vector"

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


class WwtConfig(BaseModel):
    """WWT 전역 설정."""

    home_dir: Path = WWT_HOME
    data_dir: Path = WWT_DATA_DIR
    chroma_path: Path = CHROMA_DB_PATH
    embedding_model: str = EMBEDDING_MODEL
```

**Step 2: Run full tests to catch any imports**

Run: `uv run pytest -v`
Expected: Some tests may fail due to imports — fix in next tasks

**Step 3: Commit**

```bash
git add src/whatwasthat/config.py
git commit -m "refactor(config): Ollama/Kuzu 설정 제거"
```

---

### Task 7: cli/app.py — 새 파이프라인 반영

**Files:**
- Modify: `src/whatwasthat/cli/app.py`

**Step 1: Write minimal implementation**

```python
"""wwt CLI 앱 - typer 기반 명령어 인터페이스."""

from pathlib import Path

import typer

from whatwasthat.config import WwtConfig

app = typer.Typer(
    name="wwt",
    help="whatwasthat - AI 대화 기억 검색",
)


def _get_config() -> WwtConfig:
    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


@app.command()
def init() -> None:
    """WWT 초기 설정 (DB 디렉토리 생성)."""
    config = _get_config()
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()
    typer.echo(f"WWT 초기화 완료: {config.home_dir}")


@app.command()
def ingest(path: str = typer.Argument(help="JSONL 파일 또는 디렉토리 경로")) -> None:
    """대화 로그를 벡터 DB로 적재."""
    config = _get_config()
    file_path = Path(path).expanduser()

    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import parse_jsonl, parse_session_dir, parse_session_meta
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()

    # 파싱
    if file_path.is_dir():
        sessions = parse_session_dir(file_path)
        meta_map = {
            f.stem: parse_session_meta(f)
            for f in sorted(file_path.glob("*.jsonl"))
        }
    else:
        session_id = file_path.stem
        sessions = {session_id: parse_jsonl(file_path)}
        meta_map = {session_id: parse_session_meta(file_path)}

    total_chunks = 0
    for si, (session_id, turns) in enumerate(sessions.items(), 1):
        if not turns:
            continue
        meta = meta_map.get(session_id)
        project_label = meta.project if meta else session_id[:12]
        typer.echo(f"\n[{si}/{len(sessions)}] {project_label} ({len(turns)} 턴)")

        chunks = chunk_turns(turns, session_id=session_id, meta=meta)
        if not chunks:
            typer.echo("  → 유효한 청크 없음 (스킵)")
            continue
        typer.echo(f"  → {len(chunks)}개 청크 벡터화")
        vector.upsert_chunks(chunks)
        total_chunks += len(chunks)

    typer.echo(f"\n완료: {len(sessions)} 세션, {total_chunks} 청크 저장")


@app.command()
def search(
    query: str = typer.Argument(help="검색 쿼리"),
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 필터"),
    all_projects: bool = typer.Option(False, "--all", "-a", help="전체 프로젝트 검색"),
) -> None:
    """과거 대화에서 관련 기억 검색."""
    config = _get_config()

    from whatwasthat.search.engine import SearchEngine
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()

    engine = SearchEngine(vector=vector)
    filter_project = None if all_projects else project
    results = engine.search(query, project=filter_project)

    if not results:
        typer.echo("관련 기억을 찾지 못했습니다.")
        return

    typer.echo(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")
    for i, result in enumerate(results, 1):
        branch_tag = f" ({result.git_branch})" if result.git_branch else ""
        header = f"  {i}. {result.project}{branch_tag} (점수: {result.score:.2f})"
        typer.echo(header)
        for chunk in result.chunks[:3]:
            # 청크 원문에서 첫 2줄만 표시
            lines = chunk.raw_text.strip().split("\n")[:2]
            for line in lines:
                typer.echo(f"     {line[:100]}")
        typer.echo()


@app.command()
def watch() -> None:
    """백그라운드 데몬 - 새 대화 자동 감지. (Phase 2)"""
    typer.echo("watch 기능은 Phase 2에서 구현 예정입니다.")
```

**Step 2: Run to verify**

Run: `uv run wwt --help`
Expected: CLI help output with init, ingest, search, watch commands

**Step 3: Commit**

```bash
git add src/whatwasthat/cli/app.py
git commit -m "refactor(cli): 트리플 파이프라인 → 청크 벡터화 파이프라인 전환"
```

---

### Task 8: 불필요 파일 삭제 + 테스트 정리

**Files:**
- Delete: `src/whatwasthat/pipeline/extractor.py`
- Delete: `src/whatwasthat/pipeline/prompts.py`
- Delete: `src/whatwasthat/pipeline/resolver.py`
- Delete: `src/whatwasthat/pipeline/entity.py`
- Delete: `src/whatwasthat/storage/graph.py`
- Delete: `src/whatwasthat/server/mcp.py`
- Delete: `tests/test_pipeline/test_extractor.py`
- Delete: `tests/test_pipeline/test_resolver.py`
- Delete: `tests/test_pipeline/test_entity.py`
- Delete: `tests/test_storage/test_graph.py`

**Step 1: Delete files**

```bash
rm src/whatwasthat/pipeline/extractor.py
rm src/whatwasthat/pipeline/prompts.py
rm src/whatwasthat/pipeline/resolver.py
rm src/whatwasthat/pipeline/entity.py
rm src/whatwasthat/storage/graph.py
rm src/whatwasthat/server/mcp.py
rm tests/test_pipeline/test_extractor.py
rm tests/test_pipeline/test_resolver.py
rm tests/test_pipeline/test_entity.py
rm tests/test_storage/test_graph.py
```

**Step 2: Run all tests**

Run: `uv run pytest -v`
Expected: PASS (remaining tests — models, parser, chunker, vector, engine)

**Step 3: Commit**

```bash
git add -A
git commit -m "refactor: Triple 파이프라인 모듈 삭제 (extractor, prompts, resolver, entity, graph)"
```

---

### Task 9: pyproject.toml — 의존성 제거 + 설명 수정

**Files:**
- Modify: `pyproject.toml`

**Step 1: Update dependencies**

`pyproject.toml`에서:
- `kuzu>=0.9` 삭제
- `ollama>=0.4` 삭제
- `description` 수정
- `prompts.py` ruff 예외 삭제

```toml
[project]
name = "whatwasthat"
version = "0.2.0"
description = "AI 대화 기억 검색 — LLM 대화 로그를 벡터화하여 시맨틱 검색"
requires-python = ">=3.12"
license = "MIT"

dependencies = [
    "typer>=0.15",
    "chromadb>=0.6",
    "sentence-transformers>=3.3",
    "pydantic>=2.10",
    "mcp>=1.0",
]

[project.scripts]
wwt = "whatwasthat.cli.app:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/whatwasthat"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.9",
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 2: Sync dependencies**

Run: `uv sync`
Expected: kuzu, ollama removed from environment

**Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: PASS (all remaining tests)

**Step 4: Lint**

Run: `uv run ruff check src/ tests/`
Expected: No errors

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "refactor: ollama/kuzu 의존성 제거, v0.2.0 벡터 검색 전환"
```

---

### Task 10: E2E 검증 — ingest + search 동작 확인

**Step 1: 데이터 초기화**

```bash
rm -rf ~/.wwt/data
uv run wwt init
```

**Step 2: Ingest 실행**

```bash
uv run wwt ingest ~/.claude/projects/-Users-hyuk-PycharmProjects-TipOfMyTongue/418c7b60-6950-4311-939d-0503ba6f97ab.jsonl
```

Expected: 수 초 내 완료 (Ollama 없이)

**Step 3: Search 테스트**

```bash
uv run wwt search "DB 선택"
uv run wwt search "프로젝트 이름"
uv run wwt search "프레임워크"
```

Expected: 쿼리마다 다른 관련 대화 청크 표시, 프로젝트명/브랜치 표시

**Step 4: 최종 전체 테스트**

```bash
uv run pytest -v
uv run ruff check src/ tests/
```

Expected: All tests pass, no lint errors

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: v0.2.0 벡터 검색 전환 완료 — E2E 검증 통과"
```
