"""대명사 해소 - 지시어/대명사를 실제 명칭으로 치환."""

from whatwasthat.models import Chunk


def resolve_references(chunk: Chunk) -> Chunk:
    """Chunk 내 대명사/지시어를 실제 명칭으로 치환.

    1차: 규칙 기반 (패턴 매칭)
    2차: LLM 해소 (규칙으로 못 잡은 것만 Ollama에 전달)
    """
    pass
