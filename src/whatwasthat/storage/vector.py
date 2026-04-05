"""ChromaDB 벡터 DB 래퍼 - 청크 원문 임베딩, 하이브리드 검색(벡터 + BM25)."""

from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from rank_bm25 import BM25Okapi

from whatwasthat.config import EMBEDDING_MODEL
from whatwasthat.models import Chunk

# 하이브리드 검색 가중치: vector * α + bm25 * (1-α)
_VECTOR_WEIGHT = 0.6


def _tokenize(text: str) -> list[str]:
    """간단한 공백 + 구두점 기반 토크나이저."""
    import re
    return re.findall(r"[가-힣a-zA-Z0-9]+", text.lower())


class VectorStore:
    """ChromaDB 청크 벡터 검색 + BM25 하이브리드."""

    COLLECTION_NAME = "wwt_chunks"

    def __init__(self, db_path: Path, model_name: str = EMBEDDING_MODEL) -> None:
        self._db_path = db_path
        self._model_name = model_name
        self._client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: list[str] = []
        self._bm25_metas: list[dict] = []

    def initialize(self) -> None:
        self._db_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._db_path))
        ef = SentenceTransformerEmbeddingFunction(model_name=self._model_name)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
            embedding_function=ef,
        )
        self._build_bm25_index()

    def _get_collection(self) -> chromadb.Collection:
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")
        return self._collection

    def _build_bm25_index(self) -> None:
        """ChromaDB에 저장된 문서로 BM25 인덱스 구축."""
        collection = self._get_collection()
        if collection.count() == 0:
            self._bm25 = None
            self._bm25_ids = []
            self._bm25_metas = []
            return
        all_data = collection.get(include=["documents", "metadatas"])
        docs = all_data.get("documents") or []
        self._bm25_ids = all_data.get("ids") or []
        self._bm25_metas = all_data.get("metadatas") or []
        tokenized = [_tokenize(doc) for doc in docs]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

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
        # BM25 인덱스 재구축
        self._build_bm25_index()

    def search(
        self,
        query: str,
        top_k: int = 10,
        project: str | None = None,
    ) -> list[tuple[str, float, dict]]:
        collection = self._get_collection()
        if collection.count() == 0:
            return []

        # 1. 벡터 검색
        actual_k = min(top_k, collection.count())
        where = {"project": project} if project else None
        vec_results = collection.query(
            query_texts=[query],
            n_results=actual_k,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

        vec_scores: dict[str, float] = {}
        vec_metas: dict[str, dict] = {}
        if vec_results["ids"] and vec_results["distances"]:
            for chunk_id, distance, meta in zip(
                vec_results["ids"][0],
                vec_results["distances"][0],
                vec_results["metadatas"][0],
            ):
                vec_scores[chunk_id] = max(0.0, 1.0 - distance)
                vec_metas[chunk_id] = meta

        # 2. BM25 검색
        bm25_scores: dict[str, float] = {}
        if self._bm25 and self._bm25_ids:
            query_tokens = _tokenize(query)
            if query_tokens:
                raw_scores = self._bm25.get_scores(query_tokens)
                max_bm25 = max(raw_scores) if max(raw_scores) > 0 else 1.0
                for i, score in enumerate(raw_scores):
                    cid = self._bm25_ids[i]
                    meta = self._bm25_metas[i] if i < len(self._bm25_metas) else {}
                    # 프로젝트 필터 적용
                    if project and meta.get("project") != project:
                        continue
                    if score > 0:
                        bm25_scores[cid] = score / max_bm25
                        if cid not in vec_metas:
                            vec_metas[cid] = meta

        # 3. 하이브리드 점수 결합
        all_ids = set(vec_scores.keys()) | set(bm25_scores.keys())
        combined: list[tuple[str, float, dict]] = []
        for cid in all_ids:
            v_score = vec_scores.get(cid, 0.0)
            b_score = bm25_scores.get(cid, 0.0)
            hybrid = v_score * _VECTOR_WEIGHT + b_score * (1 - _VECTOR_WEIGHT)
            combined.append((cid, hybrid, vec_metas.get(cid, {})))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]
