"""하이브리드 검색 엔진 - ChromaDB 시맨틱 검색 + Kuzu 그래프 확장."""

from whatwasthat.models import SearchResult
from whatwasthat.storage.graph import GraphStore
from whatwasthat.storage.vector import VectorStore


class SearchEngine:
    """벡터 + 그래프 하이브리드 검색."""

    def __init__(self, graph: GraphStore, vector: VectorStore) -> None:
        self._graph = graph
        self._vector = vector

    def search(self, query: str, time_range: str | None = None) -> list[SearchResult]:
        """하이브리드 검색: 벡터 시맨틱 → 그래프 확장 → 세션 그루핑."""
        # 1. 벡터 검색으로 관련 엔티티 찾기
        vector_hits = self._vector.search(query, top_k=10)
        if not vector_hits:
            return []

        # 2. 엔티티명으로 변환
        collection = self._vector._get_collection()
        entity_ids = [hit[0] for hit in vector_hits]
        entity_data = collection.get(ids=entity_ids)
        entity_names = [
            meta["name"]
            for meta in (entity_data.get("metadatas") or [])
            if meta
        ]

        if not entity_names:
            return []

        # 3. 그래프에서 관련 세션 찾기
        sessions = self._graph.find_related_sessions(entity_names)
        if not sessions:
            return []

        # 4. 세션별 트리플 수집 + SearchResult 생성
        results: list[SearchResult] = []
        score_map = {hit[0]: hit[1] for hit in vector_hits}

        for session in sessions:
            triples = self._graph.get_session_triples(session.id)
            best_score = max(
                (score_map.get(eid, 0.0) for eid in entity_ids),
                default=0.0,
            )
            summary_parts = [
                f"{t.subject} {t.predicate} {t.object}"
                for t in triples[:3]
            ]
            results.append(SearchResult(
                session_id=session.id,
                triples=triples,
                summary=" | ".join(summary_parts),
                score=max(0.0, min(1.0, best_score)),
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results
