"""vector 모듈 테스트."""

from whatwasthat.storage.vector import VectorStore
from whatwasthat.models import Entity


class TestVectorStore:
    def test_initialize(self, tmp_data_dir):
        store = VectorStore(tmp_data_dir / "vector")
        store.initialize()
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
        entity_ids = [r[0] for r in results]
        assert "e1" in entity_ids[:2] or "e2" in entity_ids[:2]
