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
        pass
