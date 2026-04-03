"""graph 모듈 테스트."""

from whatwasthat.models import Triple
from whatwasthat.storage.graph import GraphStore


class TestGraphStore:
    def test_initialize_creates_schema(self, tmp_data_dir):
        store = GraphStore(tmp_data_dir / "graph")
        store.initialize()
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
