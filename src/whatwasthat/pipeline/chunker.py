"""주제 기반 청킹 - Turn 리스트를 의미 단위 Chunk로 분리."""

from __future__ import annotations

import hashlib

from whatwasthat.models import Chunk, SessionMeta, Turn

# 최소 raw_text 길이 — 너무 짧은 청크는 추출할 게 없음
_MIN_CHUNK_CHARS = 200

# 기본 오버랩 턴 수
_DEFAULT_OVERLAP = 2


def _make_chunk_id(session_id: str, start_index: int) -> str:
    """세션 ID + 시작 턴 인덱스로 결정적 청크 ID 생성."""
    raw = f"{session_id}:c{start_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chunk_turns(
    turns: list[Turn],
    session_id: str,
    min_turns: int = 2,
    max_turns: int = 6,
    overlap: int = _DEFAULT_OVERLAP,
    meta: SessionMeta | None = None,
) -> list[Chunk]:
    """Turn 리스트를 오버랩 슬라이딩 윈도우로 Chunk 분리.

    overlap만큼 이전 청크와 턴을 겹쳐서 맥락을 보존한다.
    예: max_turns=6, overlap=2 → [0:6], [4:10], [8:14]
    """
    if not turns:
        return []

    project = meta.project if meta else ""
    project_path = meta.project_path if meta else ""
    git_branch = meta.git_branch if meta else ""
    source = meta.source if meta else "claude-code"
    timestamp = meta.started_at if meta else None

    step = max(1, max_turns - overlap)
    chunks: list[Chunk] = []
    for i in range(0, len(turns), step):
        batch = turns[i : i + max_turns]
        if len(batch) < min_turns:
            continue
        raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in batch)
        has_user = any(t.role == "user" for t in batch)
        if not has_user or len(raw_text) < _MIN_CHUNK_CHARS:
            continue
        code_snippets: list[dict[str, str]] = []
        for turn in batch:
            code_snippets.extend(turn.code_snippets)
        chunks.append(Chunk(
            id=_make_chunk_id(session_id, i),
            session_id=session_id,
            turns=batch,
            raw_text=raw_text,
            timestamp=timestamp,
            project=project,
            project_path=project_path,
            git_branch=git_branch,
            source=source,
            code_snippets=code_snippets,
            start_turn_index=i,
        ))
    return chunks
