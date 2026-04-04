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
