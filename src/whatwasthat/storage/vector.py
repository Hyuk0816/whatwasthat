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
                score = 1.0 - distance
                pairs.append((entity_id, score))
        return pairs
