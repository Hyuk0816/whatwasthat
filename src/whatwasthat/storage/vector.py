"""ChromaDB 벡터 DB 래퍼 - 임베딩, upsert, 시맨틱 검색."""

from pathlib import Path

from whatwasthat.models import Entity


class VectorStore:
    """ChromaDB 벡터 검색 래퍼."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        """ChromaDB 컬렉션 초기화."""
        pass

    def upsert_entities(self, entities: list[Entity]) -> None:
        """엔티티 임베딩 저장/갱신."""
        pass

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """시맨틱 검색 - (entity_id, score) 리스트 반환."""
        pass
