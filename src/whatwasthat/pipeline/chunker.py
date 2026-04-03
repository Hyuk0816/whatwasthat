"""주제 기반 청킹 - Turn 리스트를 의미 단위 Chunk로 분리."""

from whatwasthat.models import Chunk, Turn


def chunk_turns(turns: list[Turn], min_turns: int = 3, max_turns: int = 10) -> list[Chunk]:
    """Turn 리스트를 주제 전환 지점에서 Chunk로 분리."""
    pass
