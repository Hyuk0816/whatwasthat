"""주제 기반 청킹 - Turn 리스트를 의미 단위 Chunk로 분리."""

import uuid

from whatwasthat.models import Chunk, SessionMeta, Turn

# 최소 raw_text 길이 — 너무 짧은 청크는 추출할 게 없음
_MIN_CHUNK_CHARS = 200


def chunk_turns(
    turns: list[Turn],
    session_id: str,
    min_turns: int = 3,
    max_turns: int = 6,
    meta: SessionMeta | None = None,
) -> list[Chunk]:
    """Turn 리스트를 Chunk로 분리.

    PoC: max_turns 기준 슬라이딩 윈도우. 고급 주제 감지는 Phase 3.
    meta가 있으면 각 Chunk에 project/project_path/git_branch를 전파.
    """
    if not turns:
        return []

    project = meta.project if meta else ""
    project_path = meta.project_path if meta else ""
    git_branch = meta.git_branch if meta else ""

    chunks: list[Chunk] = []
    for i in range(0, len(turns), max_turns):
        batch = turns[i : i + max_turns]
        raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in batch)
        # user 턴이 없거나 텍스트가 너무 짧으면 스킵
        has_user = any(t.role == "user" for t in batch)
        if not has_user or len(raw_text) < _MIN_CHUNK_CHARS:
            continue
        chunks.append(Chunk(
            id=str(uuid.uuid4())[:8],
            session_id=session_id,
            turns=batch,
            raw_text=raw_text,
            project=project,
            project_path=project_path,
            git_branch=git_branch,
        ))
    return chunks
