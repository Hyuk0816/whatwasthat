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
