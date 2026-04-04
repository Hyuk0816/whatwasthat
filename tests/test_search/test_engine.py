"""search engine 모듈 테스트."""

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
            Chunk(id="ch1", session_id="s1",
                  turns=[Turn(role="user", content="DB는 Kuzu로 선택했어")],
                  raw_text="[user]: DB는 Kuzu로 선택했어",
                  project="myproject", git_branch="main"),
        ]
        vector.upsert_chunks(chunks)
        results = engine.search("데이터베이스")
        assert len(results) > 0
        assert results[0].session_id == "s1"
        assert results[0].project == "myproject"

    def test_search_groups_by_session(self, tmp_data_dir):
        engine, vector = self._make_engine(tmp_data_dir)
        chunks = [
            Chunk(id="ch1", session_id="s1",
                  turns=[Turn(role="user", content="DB는 Kuzu로")],
                  raw_text="[user]: DB는 Kuzu로", project="proj", git_branch="main"),
            Chunk(id="ch2", session_id="s1",
                  turns=[Turn(role="user", content="벡터는 ChromaDB로")],
                  raw_text="[user]: 벡터는 ChromaDB로", project="proj", git_branch="main"),
            Chunk(id="ch3", session_id="s2",
                  turns=[Turn(role="user", content="프론트는 React로")],
                  raw_text="[user]: 프론트는 React로", project="proj", git_branch="dev"),
        ]
        vector.upsert_chunks(chunks)
        results = engine.search("DB 선택")
        session_ids = [r.session_id for r in results]
        assert len(session_ids) == len(set(session_ids))

    def test_search_empty_db(self, tmp_data_dir):
        engine, _ = self._make_engine(tmp_data_dir)
        assert engine.search("아무거나") == []

    def test_search_with_project_filter(self, tmp_data_dir):
        engine, vector = self._make_engine(tmp_data_dir)
        chunks = [
            Chunk(id="ch1", session_id="s1", turns=[Turn(role="user", content="DB는 Kuzu로")],
                  raw_text="[user]: DB는 Kuzu로", project="projectA", git_branch="main"),
            Chunk(id="ch2", session_id="s2", turns=[Turn(role="user", content="DB는 PostgreSQL로")],
                  raw_text="[user]: DB는 PostgreSQL로", project="projectB", git_branch="main"),
        ]
        vector.upsert_chunks(chunks)
        results = engine.search("DB", project="projectA")
        assert all(r.project == "projectA" for r in results)
