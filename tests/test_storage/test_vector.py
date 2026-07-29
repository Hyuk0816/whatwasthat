"""vector 모듈 테스트."""

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
            Chunk(id="ch1", session_id="s1",
                  turns=[Turn(role="user", content="DB는 Kuzu로 하자")],
                  raw_text="[user]: DB는 Kuzu로 하자",
                  project="myproject", git_branch="main"),
        ]
        store.upsert_chunks(chunks)
        assert store._get_collection().count() == 1

    def test_search_returns_results(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(id="ch1", session_id="s1",
                  turns=[Turn(role="user", content="DB는 Kuzu를 선택했어")],
                  raw_text="[user]: DB는 Kuzu를 선택했어",
                  project="myproject", git_branch="main"),
            Chunk(id="ch2", session_id="s1",
                  turns=[Turn(role="user", content="프론트엔드는 React로 가자")],
                  raw_text="[user]: 프론트엔드는 React로 가자",
                  project="myproject", git_branch="main"),
        ]
        store.upsert_chunks(chunks)
        results = store.search("데이터베이스 선택", top_k=2)
        assert len(results) > 0
        # 3-tuple: (chunk_id, score, metadata)
        assert len(results[0]) == 3

    def test_search_with_project_filter(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(id="ch1", session_id="s1", turns=[], project="projectA",
                  raw_text="DB는 Kuzu를 선택", git_branch="main"),
            Chunk(id="ch2", session_id="s2", turns=[], project="projectB",
                  raw_text="DB는 PostgreSQL 선택", git_branch="main"),
        ]
        store.upsert_chunks(chunks)
        results = store.search("DB 선택", top_k=5, project="projectA")
        assert all(r[2]["project"] == "projectA" for r in results)

    def test_search_empty_store(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        assert store.search("아무거나") == []

    def test_upsert_stores_source_metadata(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunk = Chunk(id="t1", session_id="s1", turns=[],
                      raw_text="test content " * 20, source="gemini-cli")
        store.upsert_chunks([chunk])
        result = store._get_collection().get(ids=["t1"], include=["metadatas"])
        assert result["metadatas"][0]["source"] == "gemini-cli"

    def test_search_with_source_filter(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(id="ch1", session_id="s1", turns=[], project="proj",
                  raw_text="DB는 Kuzu를 선택", git_branch="main", source="claude-code"),
            Chunk(id="ch2", session_id="s2", turns=[], project="proj",
                  raw_text="DB는 PostgreSQL 선택", git_branch="main", source="gemini-cli"),
        ]
        store.upsert_chunks(chunks)
        results = store.search("DB 선택", top_k=5, source="gemini-cli")
        assert all(r[2]["source"] == "gemini-cli" for r in results)

    def test_upsert_initializes_access_count_zero(self, tmp_data_dir):
        from whatwasthat.models import Chunk, Turn
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(id="c1", session_id="s1",
                  turns=[Turn(role="user", content="test content")],
                  raw_text="[user]: test content long enough for chunk minimum",
                  project="proj"),
        ]
        store.upsert_chunks(chunks)
        result = store._get_collection().get(ids=["c1"], include=["metadatas"])
        assert result["metadatas"][0]["access_count"] == 0

    def test_increment_access_counts(self, tmp_data_dir):
        from whatwasthat.models import Chunk, Turn
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks = [
            Chunk(id="c1", session_id="s1",
                  turns=[Turn(role="user", content="test content")],
                  raw_text="[user]: test content long enough",
                  project="proj"),
            Chunk(id="c2", session_id="s1",
                  turns=[Turn(role="user", content="another content")],
                  raw_text="[user]: another content long enough",
                  project="proj"),
        ]
        store.upsert_chunks(chunks)
        store.increment_access_counts(["c1", "c2", "c1"])  # c1 +2, c2 +1
        result = store._get_collection().get(ids=["c1", "c2"], include=["metadatas"])
        id_to_meta = {
            cid: meta for cid, meta in zip(result["ids"], result["metadatas"])
        }
        assert id_to_meta["c1"]["access_count"] == 2
        assert id_to_meta["c2"]["access_count"] == 1

    def test_project_cache_invalidated_on_upsert(self, tmp_data_dir):
        """upsert 후 프로젝트 캐시가 무효화되어 새 프로젝트를 찾을 수 있는지."""
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        chunks1 = [Chunk(id="ch1", session_id="s1", turns=[], project="ProjectA",
                         raw_text="test " * 50, git_branch="main")]
        store.upsert_chunks(chunks1)
        assert store._resolve_project("projecta") == "ProjectA"

        chunks2 = [Chunk(id="ch2", session_id="s2", turns=[], project="ProjectB",
                         raw_text="test " * 50, git_branch="main")]
        store.upsert_chunks(chunks2)
        assert store._resolve_project("projectb") == "ProjectB"


class TestDefensiveIdFilter:
    def test_search_drops_phantom_bm25_ids(self, tmp_data_dir):
        """Realistic stale BM25 race: delete from ChromaDB without rebuilding BM25.

        Simulates: process B deleted a chunk but process A's BM25 still has it.
        Without the defensive filter, the phantom ID slips through and engine.py
        crashes with "Error finding id" when it later does collection.get().

        Diverse corpus is required so BM25 IDF gives the phantom a positive score.
        """
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
        store.upsert_chunks([
            Chunk(id="c_phantom", session_id="s_phantom",
                  turns=[Turn(role="user", content="Redis 캐시 설정")],
                  raw_text="Redis 캐시 maxmemory allkeys-lru 정책 설정 " * 10,
                  project="proj"),
            Chunk(id="c_other1", session_id="s1",
                  turns=[Turn(role="user", content="React 컴포넌트")],
                  raw_text="React useState useEffect 컴포넌트 라이프사이클 " * 10,
                  project="proj"),
            Chunk(id="c_other2", session_id="s2",
                  turns=[Turn(role="user", content="PostgreSQL 인덱스")],
                  raw_text="PostgreSQL 인덱스 쿼리 옵티마이저 EXPLAIN " * 10,
                  project="proj"),
        ])
        # Direct collection.delete bypasses upsert_chunks → BM25 stale on purpose
        store._get_collection().delete(ids=["c_phantom"])
        # Pre-condition: BM25 still references the deleted ID
        assert "c_phantom" in store._bm25_ids

        # search must NOT raise; phantom must be filtered out by defensive layer
        results = store.search("Redis 캐시", top_k=5)
        result_ids = {r[0] for r in results}
        assert "c_phantom" not in result_ids, f"Phantom slipped through: {result_ids}"
