"""시맨틱 검색 엔진 - ChromaDB 벡터 검색 + 세션 그루핑."""

from collections import defaultdict

from whatwasthat.models import Chunk, SearchResult
from whatwasthat.storage.vector import VectorStore

# 최소 유사도 점수 — 이 이하는 관련 없는 결과로 간주
_MIN_SCORE = 0.5


class SearchEngine:
    """벡터 시맨틱 검색 + 세션 그루핑."""

    def __init__(self, vector: VectorStore) -> None:
        self._vector = vector

    def search(
        self,
        query: str,
        project: str | None = None,
        top_k: int = 10,
        source: str | None = None,
        git_branch: str | None = None,
    ) -> list[SearchResult]:
        hits = self._vector.search(query, top_k=top_k, project=project, source=source, git_branch=git_branch)
        if not hits:
            return []

        # 최소 점수 필터
        hits = [(cid, score, meta) for cid, score, meta in hits if score >= _MIN_SCORE]
        if not hits:
            return []

        collection = self._vector._get_collection()
        chunk_ids = [h[0] for h in hits]
        chunk_data = collection.get(ids=chunk_ids, include=["documents", "metadatas"])

        session_chunks: defaultdict[str, list[tuple[Chunk, float]]] = defaultdict(list)
        for i, (chunk_id, score, _) in enumerate(hits):
            meta = chunk_data["metadatas"][i] if chunk_data["metadatas"] else {}
            doc = chunk_data["documents"][i] if chunk_data["documents"] else ""
            chunk = Chunk(
                id=chunk_id,
                session_id=meta.get("session_id", ""),
                turns=[],
                raw_text=doc,
                project=meta.get("project", ""),
                project_path=meta.get("project_path", ""),
                git_branch=meta.get("git_branch", ""),
                source=meta.get("source", "claude-code"),
            )
            session_chunks[chunk.session_id].append((chunk, score))

        results: list[SearchResult] = []
        for session_id, chunk_scores in session_chunks.items():
            chunk_scores.sort(key=lambda x: x[1], reverse=True)
            chunks = [c for c, _ in chunk_scores]
            best_score = chunk_scores[0][1]
            first_chunk = chunks[0]
            summary = chunks[0].raw_text[:200]
            results.append(SearchResult(
                session_id=session_id,
                chunks=chunks,
                summary=summary,
                score=best_score,
                project=first_chunk.project,
                git_branch=first_chunk.git_branch,
                source=first_chunk.source,
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results
