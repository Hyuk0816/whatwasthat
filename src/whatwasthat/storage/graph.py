"""Kuzu 그래프 DB 래퍼 - 스키마 초기화, 트리플 CRUD, Cypher 쿼리."""

from pathlib import Path

from whatwasthat.models import Entity, Session, Triple


class GraphStore:
    """Kuzu 그래프 DB 래퍼."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        """스키마 초기화 (Entity, Session, Chunk 노드 + RELATION, CONTAINS, MENTIONS 엣지)."""
        pass

    def add_triples(self, session_id: str, triples: list[Triple]) -> None:
        """세션에 트리플 리스트 저장."""
        pass

    def get_session_triples(self, session_id: str) -> list[Triple]:
        """세션의 모든 트리플 조회."""
        pass

    def get_entity_history(self, entity_name: str) -> list[Triple]:
        """엔티티의 시간순 변천 이력 조회."""
        pass

    def find_related_sessions(self, entity_ids: list[str]) -> list[Session]:
        """엔티티와 관련된 세션 목록 조회."""
        pass
