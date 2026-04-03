"""주제 기반 청킹 - Turn 리스트를 의미 단위 Chunk로 분리."""

import uuid

from whatwasthat.models import Chunk, Turn


def chunk_turns(
    turns: list[Turn],
    session_id: str,
    min_turns: int = 3,
    max_turns: int = 10,
) -> list[Chunk]:
    """Turn 리스트를 Chunk로 분리.

    PoC: max_turns 기준 슬라이딩 윈도우. 고급 주제 감지는 Phase 3.
    """
    if not turns:
        return []

    chunks: list[Chunk] = []
    for i in range(0, len(turns), max_turns):
        batch = turns[i : i + max_turns]
        raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in batch)
        chunks.append(Chunk(
            id=str(uuid.uuid4())[:8],
            session_id=session_id,
            turns=batch,
            raw_text=raw_text,
        ))
    return chunks
