"""ChromaDB 벡터 DB 래퍼 - 청크 원문 임베딩, 하이브리드 검색(벡터 + BM25)."""

from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from rank_bm25 import BM25Okapi

from whatwasthat.config import EMBEDDING_MODEL
from whatwasthat.models import Chunk

# 하이브리드 검색 가중치: vector * α + bm25 * (1-α)
_VECTOR_WEIGHT = 0.6


_kiwi = None


def _get_kiwi():
    """Kiwi 형태소 분석기 싱글톤."""
    global _kiwi  # noqa: PLW0603
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def _tokenize(text: str) -> list[str]:
    """한국어 형태소 분석(kiwipiepy) + camelCase 분리 혼합 토크나이저."""
    import re

    # 1차: camelCase 분리 (SheDataset → She Dataset)
    # 소문자→대문자+소문자 경계만 분리 (PostgreSQL의 eS는 분리하지 않음)
    text = re.sub(r"([a-z])([A-Z][a-z])", r"\1 \2", text)
    # 파일 확장자 분리 (file.vue → file vue)
    text = re.sub(r"\.([a-zA-Z]{1,5})\b", r" \1", text)

    # 2차: kiwipiepy 형태소 분석
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)

    # 의미 있는 품사만 추출: 명사(NN*), 영어(SL), 숫자(SN), 동사어간(VV/VA), 어근(XR)
    meaningful = [
        t.form.lower()
        for t in tokens
        if t.tag.startswith(("NN", "NR", "SL", "SN", "VV", "VA", "XR"))
        and len(t.form) > 1
    ]
    return meaningful


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

    def count(self) -> int:
        """저장된 청크 수 반환."""
        return self._get_collection().count()

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

    def upsert_chunks(self, chunks: list[Chunk], *, rebuild_bm25: bool = True) -> None:
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
                "source": c.source,
            }
            for i, c in enumerate(chunks)
        ]
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        if rebuild_bm25:
            self._build_bm25_index()

    def rebuild_index(self) -> None:
        """BM25 인덱스 수동 재구축 — 대량 적재 후 호출."""
        self._build_bm25_index()

    def upsert_session_chunks(
        self, session_id: str, chunks: list[Chunk], *, rebuild_bm25: bool = True,
    ) -> int:
        """세션 단위 증분 upsert — 변경된 청크만 임베딩, 오래된 중복 정리.

        Args:
            rebuild_bm25: False면 BM25 재구축 지연 (대량 적재 시 마지막에 rebuild_index() 호출).

        Returns:
            실제로 임베딩된 청크 수.
        """
        if not chunks:
            return 0

        collection = self._get_collection()

        # 1. 이 세션의 기존 청크 메타 조회
        existing = collection.get(
            where={"session_id": session_id},
            include=["metadatas"],
        )
        existing_meta: dict[str, int] = {
            cid: (meta.get("turn_count", 0) if meta else 0)
            for cid, meta in zip(existing["ids"], existing["metadatas"] or [])
        }

        # 2. 새 청크 ID 집합과 비교하여 stale 항목 삭제 (랜덤 UUID 중복 정리)
        new_ids = {c.id for c in chunks}
        stale_ids = [cid for cid in existing_meta if cid not in new_ids]
        if stale_ids:
            collection.delete(ids=stale_ids)

        # 3. 변경된 청크만 필터 — ID 동일 + turn_count 동일이면 스킵
        changed: list[Chunk] = []
        for chunk in chunks:
            old_turn_count = existing_meta.get(chunk.id)
            if old_turn_count is not None and old_turn_count == len(chunk.turns):
                continue  # 내용 동일, 임베딩 스킵
            changed.append(chunk)

        # 4. 변경분만 upsert (임베딩은 여기서만 발생)
        if changed:
            self.upsert_chunks(changed, rebuild_bm25=rebuild_bm25)
        elif stale_ids:
            # stale 삭제만 했으면 BM25 재구축 필요
            self._build_bm25_index()

        return len(changed)

    def search(
        self,
        query: str,
        top_k: int = 10,
        project: str | None = None,
        source: str | None = None,
    ) -> list[tuple[str, float, dict]]:
        collection = self._get_collection()
        if collection.count() == 0:
            return []

        # 후보 풀 크기 — 벡터/BM25 각각 top_k*3을 가져와서 합집합
        candidate_k = min(top_k * 3, collection.count())

        # 1. 벡터 검색
        conditions: dict[str, str] = {}
        if project:
            conditions["project"] = project
        if source:
            conditions["source"] = source
        where = conditions if conditions else None
        vec_results = collection.query(
            query_texts=[query],
            n_results=candidate_k,
            where=where,
            include=["metadatas", "distances"],
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

        # 2. BM25 검색 — 상위 candidate_k개만 사용
        bm25_scores: dict[str, float] = {}
        if self._bm25 and self._bm25_ids:
            query_tokens = _tokenize(query)
            if query_tokens:
                raw_scores = self._bm25.get_scores(query_tokens)
                max_bm25 = max(raw_scores) if max(raw_scores) > 0 else 1.0
                import numpy as np
                top_indices = np.argsort(raw_scores)[-candidate_k:][::-1]
                for idx in top_indices:
                    score = raw_scores[idx]
                    if score <= 0:
                        break
                    cid = self._bm25_ids[idx]
                    meta = self._bm25_metas[idx] if idx < len(self._bm25_metas) else {}
                    if project and meta.get("project") != project:
                        continue
                    if source and meta.get("source") != source:
                        continue
                    bm25_scores[cid] = score / max_bm25
                    if cid not in vec_metas:
                        vec_metas[cid] = meta

        # 3. 하이브리드 점수 결합 — 합집합의 양쪽 점수 결합
        all_ids = set(vec_scores.keys()) | set(bm25_scores.keys())
        combined: list[tuple[str, float, dict]] = []
        for cid in all_ids:
            v_score = vec_scores.get(cid, 0.0)
            b_score = bm25_scores.get(cid, 0.0)
            hybrid = v_score * _VECTOR_WEIGHT + b_score * (1 - _VECTOR_WEIGHT)
            combined.append((cid, hybrid, vec_metas.get(cid, {})))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]
