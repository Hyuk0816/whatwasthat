"""시맨틱 검색 엔진 - ChromaDB 벡터 검색 + 세션 그루핑.

3축 가중합 스코어링 (Generative Agents 2023 기반):
    final_score = relevance × (w_rel + w_rec × recency + w_imp × importance)

- relevance: 하이브리드 검색 점수 (vector × 0.6 + bm25 × 0.4)
- recency:   시간 감쇠 (1 - 0.003)^hours_passed
- importance: 패턴 기반 중요도 (의사결정/에러/아키텍처)

OP-RAG 순서 보존: decision/memory 모드는 청크를 turn 순서(시간순)로 정렬.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone

from whatwasthat.models import Chunk, SearchResult
from whatwasthat.storage.vector import VectorStore
from whatwasthat.timeutil import kst_day_bounds

# 최소 유사도 점수 — 이 이하는 관련 없는 결과로 간주
_MIN_SCORE = 0.5

# 의사결정 패턴 (중요도 + decision 모드 부스팅)
_DECISION_PATTERNS_KO = re.compile(r"대신|선택|결정|이유|비교|으로 갔|하기로|보다|때문에|장단점")
_DECISION_PATTERNS_EN = re.compile(
    r"instead of|chose|decided|because|compared|trade-?off|prefer|rather than",
    re.IGNORECASE,
)

# 에러/버그/디버깅 패턴
_ERROR_PATTERNS = re.compile(
    r"error|bug|traceback|exception|에러|버그|오류|해결|fix|debug",
    re.IGNORECASE,
)

# 아키텍처/설계 패턴
_ARCH_PATTERNS = re.compile(
    r"architect|design|pattern|refactor|설계|구조|아키텍처|리팩토링",
    re.IGNORECASE,
)

# 모드별 3축 가중치 프리셋
_SCORING_WEIGHTS: dict[str, dict[str, float]] = {
    "memory": {"w_rel": 0.60, "w_rec": 0.25, "w_imp": 0.15, "decay_rate": 0.003},
    "decision": {"w_rel": 0.50, "w_rec": 0.15, "w_imp": 0.35, "decay_rate": 0.002},
    "code": {"w_rel": 0.55, "w_rec": 0.35, "w_imp": 0.10, "decay_rate": 0.005},
}
_DEFAULT_WEIGHTS = _SCORING_WEIGHTS["memory"]


def _time_decay(hours_passed: float, decay_rate: float) -> float:
    """지수 시간 감쇠 (LangChain 방식). hours_passed 음수면 1.0 반환."""
    if hours_passed <= 0:
        return 1.0
    return (1.0 - decay_rate) ** hours_passed


def _adjusted_decay_rate(base_rate: float, access_count: int) -> float:
    """접근 횟수에 따라 감쇠율을 낮춤 (Spaced Repetition).

    access_count가 많을수록 decay_rate가 작아져 기억이 오래 유지된다.
    - access=0:  base_rate 그대로
    - access=5:  base_rate / 1.5
    - access=10: base_rate / 2.0
    - access=20: base_rate / 3.0
    """
    if access_count <= 0:
        return base_rate
    return base_rate / (1.0 + 0.1 * access_count)


def _compute_importance(text: str) -> float:
    """패턴 기반 중요도 스코어 (0.0~1.0). LLM 호출 없이 즉시 계산."""
    if not text:
        return 0.3

    score = 0.3  # 기본값
    has_important_pattern = False

    # 의사결정 패턴 (최고 중요도)
    if _DECISION_PATTERNS_KO.search(text) or _DECISION_PATTERNS_EN.search(text):
        score = max(score, 0.85)
        has_important_pattern = True

    # 에러/디버깅 (높은 중요도)
    if _ERROR_PATTERNS.search(text):
        score = max(score, 0.75)
        has_important_pattern = True

    # 아키텍처/설계 (높은 중요도)
    if _ARCH_PATTERNS.search(text):
        score = max(score, 0.70)
        has_important_pattern = True

    # 코드 블록 밀도 (중간 중요도)
    if text.count("```") >= 4:
        score = max(score, 0.55)

    # 짧은 일상 대화 억제 — 중요 패턴 없을 때만 적용
    # (짧지만 결정적인 텍스트 "Postgres로 가자"는 그대로 유지)
    if not has_important_pattern:
        word_count = len(text.split())
        if word_count < 10:
            score = min(score, 0.4)

    return min(score, 1.0)


def _apply_scoring(
    relevance: float,
    chunk_text: str,
    chunk_timestamp: datetime | None,
    mode: str | None,
    now: datetime,
    access_count: int = 0,
) -> float:
    """3축 가중합으로 최종 점수 계산. Generative Agents 2023 방식.

    access_count가 높을수록 recency 감쇠가 느려짐 (Spaced Repetition).
    """
    weights = _SCORING_WEIGHTS.get(mode or "memory", _DEFAULT_WEIGHTS)

    # recency (접근 빈도 보정된 감쇠율 사용)
    effective_decay = _adjusted_decay_rate(weights["decay_rate"], access_count)
    if chunk_timestamp is not None:
        # timezone 정규화 — naive datetime은 UTC로 간주
        if chunk_timestamp.tzinfo is None:
            chunk_ts = chunk_timestamp.replace(tzinfo=timezone.utc)
        else:
            chunk_ts = chunk_timestamp
        hours_passed = (now - chunk_ts).total_seconds() / 3600
        recency = _time_decay(hours_passed, effective_decay)
    else:
        recency = 0.5  # 타임스탬프 없으면 중간값

    # importance
    importance = _compute_importance(chunk_text)

    # 가중합
    multiplier = (
        weights["w_rel"]
        + weights["w_rec"] * recency
        + weights["w_imp"] * importance
    )
    final = relevance * multiplier
    return min(max(final, 0.0), 1.0)


class SearchEngine:
    """벡터 시맨틱 검색 + 세션 그루핑."""

    # Self-ROUTE 라우팅 임계값 (EMNLP 2024)
    _HIGH_SCORE_THRESHOLD = 0.70  # 이 이상이면 1차 결과로 충분
    _MEDIUM_SCORE_THRESHOLD = 0.55  # 이 이상이면 decision 모드 병행

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
        date: str | None = None,
    ) -> list[SearchResult]:
        # Convenience: "YYYY-MM-DD" → UTC 하루 범위 epoch로 변환
        since_epoch: int | None = None
        until_epoch: int | None = None
        if date:
            try:
                since_epoch, until_epoch = kst_day_bounds(date)
            except ValueError as e:
                raise ValueError(
                    f"Invalid date format (expected YYYY-MM-DD): {date}",
                ) from e

        hits = self._vector.search(
            query, top_k=top_k, project=project, source=source, git_branch=git_branch,
            since_epoch=since_epoch, until_epoch=until_epoch,
        )
        if not hits:
            return []

        # 최소 점수 필터 (원본 relevance 기준)
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

        # chunk_id → chunk_data 인덱스 매핑
        id_to_idx: dict[str, int] = {cid: i for i, cid in enumerate(chunk_data["ids"])}
        existing_chunk_ids: set[str] = set(id_to_idx.keys())

        now = datetime.now(timezone.utc)

        # 3축 가중합 스코어링 적용 (relevance × (w_rel + w_rec×recency + w_imp×importance))
        session_chunks: defaultdict[str, list[tuple[Chunk, float, int]]] = defaultdict(list)
        for chunk_id, relevance, _ in hits:
            # 방어적 skip: vector.search가 phantom ID를 흘려보냈다면 건너뜀
            # (belt-and-suspenders — vector.py의 defensive filter 다음 2차 방어선)
            if chunk_id not in existing_chunk_ids:
                continue
            idx = id_to_idx.get(chunk_id, -1)
            meta = chunk_data["metadatas"][idx] if idx >= 0 and chunk_data["metadatas"] else {}
            doc = chunk_data["documents"][idx] if idx >= 0 and chunk_data["documents"] else ""

            # meta에서 timestamp 복원
            ts_str = meta.get("timestamp", "")
            chunk_ts: datetime | None = None
            if ts_str:
                try:
                    chunk_ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    chunk_ts = None

            # access_count 메타에서 복원 (Spaced Repetition)
            access_count = int(meta.get("access_count", 0) or 0)

            # 최종 점수 계산 (3축 가중합 + access-boosted decay)
            final_score = _apply_scoring(
                relevance, doc, chunk_ts, mode, now, access_count=access_count,
            )

            # 세션 내 청크 위치 (OP-RAG 순서 보존용)
            chunk_index = int(meta.get("chunk_index", 0) or 0)
            raw_preview = meta.get("raw_preview") or doc
            raw_length = int(meta.get("raw_length", len(raw_preview)) or 0)
            raw_snippet_ids = meta.get("snippet_ids", "[]")
            try:
                if isinstance(raw_snippet_ids, str):
                    snippet_ids = list(json.loads(raw_snippet_ids or "[]"))
                elif isinstance(raw_snippet_ids, list):
                    snippet_ids = raw_snippet_ids
                else:
                    snippet_ids = []
            except json.JSONDecodeError:
                snippet_ids = []
            raw_code_languages = meta.get("code_languages", "")
            if isinstance(raw_code_languages, list):
                code_languages = raw_code_languages
            else:
                code_languages = [
                    lang for lang in str(raw_code_languages or "").split(",")
                    if lang
                ]

            chunk = Chunk(
                id=chunk_id,
                span_id=meta.get("span_id", ""),
                session_id=meta.get("session_id", ""),
                granularity=meta.get("granularity", "small-window"),
                start_turn_index=chunk_index,
                end_turn_index=int(meta.get("end_turn_index", chunk_index) or chunk_index),
                turn_count=int(meta.get("turn_count", 0) or 0),
                search_text=doc,
                raw_preview=raw_preview,
                raw_length=raw_length,
                timestamp=chunk_ts,
                project=meta.get("project", ""),
                project_path=meta.get("project_path", ""),
                git_branch=meta.get("git_branch", ""),
                source=meta.get("source", "claude-code"),
                snippet_ids=snippet_ids,
                code_count=int(meta.get("code_count", 0) or 0),
                code_languages=code_languages,
                access_count=access_count,
            )
            session_chunks[chunk.session_id].append((chunk, final_score, chunk_index))

        results: list[SearchResult] = []
        for session_id, scored in session_chunks.items():
            # 세션의 대표 점수 = 청크 중 최고 점수
            best_score = max(s for _, s, _ in scored)

            # OP-RAG: decision/memory 모드는 시간순(turn index) 정렬 — 인과 흐름 보존
            # code 모드는 점수 순 — 가장 관련 높은 스니펫 우선
            if mode == "code":
                scored.sort(key=lambda x: x[1], reverse=True)
            else:
                scored.sort(key=lambda x: x[2])  # start_turn_index 오름차순

            chunks = [c for c, _, _ in scored]
            first_chunk = chunks[0]
            summary = first_chunk.raw_preview[:200]
            results.append(SearchResult(
                session_id=session_id,
                chunks=chunks,
                summary=summary,
                score=best_score,
                project=first_chunk.project,
                git_branch=first_chunk.git_branch,
                source=first_chunk.source,
                started_at=first_chunk.timestamp,
            ))

        results.sort(key=lambda r: r.score, reverse=True)

        return results

    def search_with_routing(
        self,
        query: str,
        project: str | None = None,
        top_k: int = 10,
        source: str | None = None,
        git_branch: str | None = None,
        mode: str | None = None,
        date: str | None = None,
    ) -> list[SearchResult]:
        """Self-ROUTE 스타일 자동 라우팅 (EMNLP 2024).

        1. 기본 검색 시도
        2. top score >= HIGH: 그대로 반환 (RAG로 충분)
        3. top score >= MEDIUM: decision 모드도 병행 → 병합
        4. top score < MEDIUM 또는 결과 없음: 프로젝트 필터 해제 → 전체 검색

        LLM 호출 없이 score 분포만으로 라우팅 판단.
        date 파라미터는 모든 하위 search 호출에 그대로 전파.
        """
        # 1차: 원래 요청 그대로
        primary = self.search(
            query, project=project, top_k=top_k,
            source=source, git_branch=git_branch, mode=mode, date=date,
        )

        top_score = primary[0].score if primary else 0.0

        # HIGH: 그대로 반환
        if top_score >= self._HIGH_SCORE_THRESHOLD:
            return primary

        # MEDIUM: decision 모드 병행 (mode가 이미 지정되었으면 스킵)
        if top_score >= self._MEDIUM_SCORE_THRESHOLD and mode is None:
            decision_hits = self.search(
                query, project=project, top_k=top_k,
                source=source, git_branch=git_branch, mode="decision", date=date,
            )
            return self._merge_by_session(primary, decision_hits, top_k)

        # LOW: 프로젝트 필터 해제 후 재검색
        if project is not None:
            expanded = self.search(
                query, project=None, top_k=top_k,
                source=source, git_branch=git_branch, mode=mode, date=date,
            )
            if expanded:
                return self._merge_by_session(primary, expanded, top_k)

        # fallback: 1차 결과 그대로 (빈 리스트일 수 있음)
        return primary

    @staticmethod
    def _merge_by_session(
        primary: list[SearchResult],
        extra: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """두 결과 리스트를 세션 ID 기준으로 병합 (중복 제거)."""
        seen: set[str] = set()
        merged: list[SearchResult] = []
        for r in primary + extra:
            if r.session_id in seen:
                continue
            seen.add(r.session_id)
            merged.append(r)
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:top_k]
