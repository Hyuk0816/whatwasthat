"""search engine 모듈 테스트."""

from whatwasthat.models import Entity, Triple
from whatwasthat.search.engine import SearchEngine
from whatwasthat.storage.graph import GraphStore
from whatwasthat.storage.vector import VectorStore


class TestSearchEngine:
    def _setup_stores(self, tmp_data_dir):
        graph = GraphStore(tmp_data_dir / "graph")
        vector = VectorStore(tmp_data_dir / "vector")
        graph.initialize()
        vector.initialize()
        return graph, vector

    def test_search_returns_results(self, tmp_data_dir):
        graph, vector = self._setup_stores(tmp_data_dir)
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
