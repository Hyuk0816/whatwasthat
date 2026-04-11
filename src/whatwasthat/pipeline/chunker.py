"""주제 기반 청킹 - Turn 리스트를 의미 단위 Chunk로 분리."""

from __future__ import annotations

import hashlib
from datetime import datetime

from whatwasthat.models import Chunk, CodeSnippet, RawSpan, SessionMeta, Turn

# 최소 raw_text 길이 — 너무 짧은 청크는 추출할 게 없음
_MIN_CHUNK_CHARS = 200

# 기본 오버랩 턴 수
_DEFAULT_OVERLAP = 2

# outline은 짧은 세션에 과하므로 4턴 이상일 때만 생성
_MIN_OUTLINE_TURNS = 4

# outline은 세션 요약용이므로 턴당 앞부분만 유지
_OUTLINE_TURN_CHARS = 200


def _make_chunk_id(session_id: str, key: str) -> str:
    """세션 ID + granularity key로 결정적 청크 ID 생성."""
    raw = f"{session_id}:{key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _make_small_window_chunk_id(session_id: str, start_index: int) -> str:
    """세션 ID + 시작 턴 인덱스로 결정적 청크 ID 생성."""
    return _make_chunk_id(session_id, f"c{start_index}")


def _make_turn_pair_chunk_id(session_id: str, start_index: int) -> str:
    """세션 ID + 시작 턴 인덱스로 결정적 turn-pair 청크 ID 생성."""
    return _make_chunk_id(session_id, f"tp{start_index}")


def _make_outline_chunk_id(session_id: str) -> str:
    """세션 ID로 결정적 session-outline 청크 ID 생성."""
    return _make_chunk_id(session_id, "outline")


def _make_small_window_span_id(session_id: str, start_index: int, end_index: int) -> str:
    """세션 ID + 턴 범위로 결정적 span ID 생성."""
    return f"{session_id}:s{start_index}e{end_index}"


def _make_turn_pair_span_id(session_id: str, start_index: int, end_index: int) -> str:
    """세션 ID + 턴 범위로 결정적 turn-pair span ID 생성."""
    return f"{session_id}:tp{start_index}e{end_index}"


def _make_outline_span_id(session_id: str) -> str:
    """세션 ID로 결정적 session-outline span ID 생성."""
    return f"{session_id}:outline"


def _format_turns(turns: list[Turn], attr: str) -> str:
    """Turn 리스트를 역할 prefix가 붙은 텍스트로 직렬화."""
    return "\n".join(
        f"[{turn.role}]: {getattr(turn, attr)}"
        for turn in turns
        if getattr(turn, attr)
    )


def _format_outline_turns(turns: list[Turn], attr: str) -> str:
    """Session outline용으로 각 턴 앞부분만 직렬화."""
    return "\n".join(
        f"[{turn.role}]: {getattr(turn, attr)[:_OUTLINE_TURN_CHARS]}"
        for turn in turns
        if getattr(turn, attr)
    )


def _meta_values(
    meta: SessionMeta | None,
) -> tuple[str, str, str, str, datetime | None]:
    """Chunk 공통 메타 필드 반환."""
    if meta is None:
        return "", "", "", "claude-code", None
    return (
        meta.project,
        meta.project_path,
        meta.git_branch,
        meta.source,
        meta.started_at,
    )


def _collect_code_metadata(
    turns: list[Turn],
    span_id: str,
) -> tuple[list[CodeSnippet], list[str], list[str]]:
    """Turn들에서 코드 스니펫과 파생 메타를 수집."""
    code_snippets: list[CodeSnippet] = []
    for turn in turns:
        code_snippets.extend(turn.code_snippets)

    normalized_snippets = [
        snippet.model_copy(update={"id": snippet.id or f"{span_id}_s{index}"})
        for index, snippet in enumerate(code_snippets)
    ]
    snippet_ids = [snippet.id for snippet in normalized_snippets]
    code_languages = sorted({snippet.language for snippet in normalized_snippets})
    return normalized_snippets, snippet_ids, code_languages


def _build_chunk_and_span(
    turns: list[Turn],
    session_id: str,
    granularity: str,
    chunk_id: str,
    span_id: str,
    start_index: int,
    end_index: int,
    raw_text: str,
    search_text: str,
    meta: SessionMeta | None,
    *,
    enforce_min_chars: bool,
) -> tuple[RawSpan, Chunk] | None:
    """RawSpan/Chunk 쌍을 공통 규칙으로 생성."""
    has_user = any(turn.role == "user" for turn in turns)
    if not has_user:
        return None
    if enforce_min_chars and len(raw_text) < _MIN_CHUNK_CHARS:
        return None

    project, project_path, git_branch, source, timestamp = _meta_values(meta)
    code_snippets, snippet_ids, code_languages = _collect_code_metadata(turns, span_id)

    span = RawSpan(
        id=span_id,
        session_id=session_id,
        start_turn_index=start_index,
        end_turn_index=end_index,
        raw_text=raw_text,
        code_snippets=code_snippets,
        snippet_ids=snippet_ids,
    )
    chunk = Chunk(
        id=chunk_id,
        span_id=span_id,
        session_id=session_id,
        granularity=granularity,
        start_turn_index=start_index,
        end_turn_index=end_index,
        turn_count=len(turns),
        search_text=search_text,
        raw_preview=raw_text[:1000],
        raw_length=len(raw_text),
        timestamp=timestamp,
        project=project,
        project_path=project_path,
        git_branch=git_branch,
        source=source,
        snippet_ids=snippet_ids,
        code_count=len(code_snippets),
        code_languages=code_languages,
    )
    return span, chunk


def _chunk_small_windows(
    turns: list[Turn],
    session_id: str,
    min_turns: int,
    max_turns: int,
    overlap: int,
    meta: SessionMeta | None,
) -> tuple[list[RawSpan], list[Chunk]]:
    """기존 sliding window 기반 small-window 청킹."""
    step = max(1, max_turns - overlap)
    spans: list[RawSpan] = []
    chunks: list[Chunk] = []

    for start_index in range(0, len(turns), step):
        batch = turns[start_index : start_index + max_turns]
        if len(batch) < min_turns:
            continue

        end_index = start_index + len(batch) - 1
        built = _build_chunk_and_span(
            batch,
            session_id,
            "small-window",
            _make_small_window_chunk_id(session_id, start_index),
            _make_small_window_span_id(session_id, start_index, end_index),
            start_index,
            end_index,
            _format_turns(batch, "raw_text"),
            _format_turns(batch, "search_text"),
            meta,
            enforce_min_chars=True,
        )
        if built is None:
            continue

        span, chunk = built
        spans.append(span)
        chunks.append(chunk)

    return spans, chunks


def _chunk_turn_pairs(
    turns: list[Turn],
    session_id: str,
    meta: SessionMeta | None,
) -> tuple[list[RawSpan], list[Chunk]]:
    """2턴 단위 turn-pair 청크 생성."""
    spans: list[RawSpan] = []
    chunks: list[Chunk] = []

    for start_index in range(0, len(turns), 2):
        batch = turns[start_index : start_index + 2]
        if len(batch) < 2:
            continue

        end_index = start_index + 1
        built = _build_chunk_and_span(
            batch,
            session_id,
            "turn-pair",
            _make_turn_pair_chunk_id(session_id, start_index),
            _make_turn_pair_span_id(session_id, start_index, end_index),
            start_index,
            end_index,
            _format_turns(batch, "raw_text"),
            _format_turns(batch, "search_text"),
            meta,
            enforce_min_chars=True,
        )
        if built is None:
            continue

        span, chunk = built
        spans.append(span)
        chunks.append(chunk)

    return spans, chunks


def _chunk_session_outline(
    turns: list[Turn],
    session_id: str,
    meta: SessionMeta | None,
) -> tuple[list[RawSpan], list[Chunk]]:
    """전체 세션을 1개 outline 청크로 생성."""
    if len(turns) < _MIN_OUTLINE_TURNS:
        return [], []

    built = _build_chunk_and_span(
        turns,
        session_id,
        "session-outline",
        _make_outline_chunk_id(session_id),
        _make_outline_span_id(session_id),
        0,
        len(turns) - 1,
        _format_outline_turns(turns, "raw_text"),
        _format_outline_turns(turns, "search_text"),
        meta,
        enforce_min_chars=False,
    )
    if built is None:
        return [], []

    span, chunk = built
    return [span], [chunk]


def chunk_turns(
    turns: list[Turn],
    session_id: str,
    min_turns: int = 2,
    max_turns: int = 6,
    overlap: int = _DEFAULT_OVERLAP,
    meta: SessionMeta | None = None,
) -> tuple[list[RawSpan], list[Chunk]]:
    """Turn 리스트를 오버랩 슬라이딩 윈도우로 Chunk 분리.

    overlap만큼 이전 청크와 턴을 겹쳐서 맥락을 보존한다.
    예: max_turns=6, overlap=2 → [0:6], [4:10], [8:14]
    """
    if not turns:
        return [], []

    spans: list[RawSpan] = []
    chunks: list[Chunk] = []

    for chunker in (
        _chunk_small_windows(turns, session_id, min_turns, max_turns, overlap, meta),
        _chunk_turn_pairs(turns, session_id, meta),
        _chunk_session_outline(turns, session_id, meta),
    ):
        chunker_spans, chunker_chunks = chunker
        spans.extend(chunker_spans)
        chunks.extend(chunker_chunks)

    return spans, chunks
