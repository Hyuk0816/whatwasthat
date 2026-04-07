"""시맨틱 검색 엔진 - ChromaDB 벡터 검색 + 세션 그루핑."""

from __future__ import annotations

import re
from collections import defaultdict

from whatwasthat.models import Chunk, SearchResult
from whatwasthat.storage.vector import VectorStore

# 최소 유사도 점수 — 이 이하는 관련 없는 결과로 간주
_MIN_SCORE = 0.5

# decision 모드: 의사결정 패턴 정규식과 점수 부스팅 계수
_DECISION_PATTERNS_KO = re.compile(r"대신|선택|결정|이유|비교|으로 갔|하기로|보다|때문에|장단점")
_DECISION_PATTERNS_EN = re.compile(
    r"instead of|chose|decided|because|compared|trade-?off|prefer|rather than",
    re.IGNORECASE,
)
_DECISION_BOOST = 1.3


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
        mode: str | None = None,
    ) -> list[SearchResult]:
        hits = self._vector.search(
            query, top_k=top_k, project=project, source=source, git_branch=git_branch,
        )
        if not hits:
            return []

        # 최소 점수 필터
        hits = [(cid, score, meta) for cid, score, meta in hits if score >= _MIN_SCORE]
        if not hits:
            return []

        # code 모드: 코드가 있는 청크만 필터
        if mode == "code":
            hits = [(cid, score, meta) for cid, score, meta in hits
                    if meta.get("has_code") == "true"]
            if not hits:
                return []

        collection = self._vector._get_collection()
        chunk_ids = [h[0] for h in hits]
        chunk_data = collection.get(ids=chunk_ids, include=["documents", "metadatas"])

        # chunk_id → chunk_data 인덱스 매핑 (decision 재정렬 후에도 안전하게 참조)
        id_to_idx: dict[str, int] = {cid: i for i, cid in enumerate(chunk_data["ids"])}

        # decision 모드: 의사결정 패턴이 있는 청크 점수 부스팅
        if mode == "decision":
            boosted: list[tuple[str, float, object]] = []
            for chunk_id, score, meta in hits:
                idx = id_to_idx.get(chunk_id, -1)
                doc = chunk_data["documents"][idx] if idx >= 0 and chunk_data["documents"] else ""
                if _DECISION_PATTERNS_KO.search(doc) or _DECISION_PATTERNS_EN.search(doc):
                    score = min(score * _DECISION_BOOST, 1.0)
                boosted.append((chunk_id, score, meta))
            hits = sorted(boosted, key=lambda x: x[1], reverse=True)

        session_chunks: defaultdict[str, list[tuple[Chunk, float]]] = defaultdict(list)
        for chunk_id, score, _ in hits:
            idx = id_to_idx.get(chunk_id, -1)
            meta = chunk_data["metadatas"][idx] if idx >= 0 and chunk_data["metadatas"] else {}
            doc = chunk_data["documents"][idx] if idx >= 0 and chunk_data["documents"] else ""
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
