"""트리플 추출 - Chunk에서 Knowledge Graph 트리플을 추출."""

from whatwasthat.models import Chunk, Triple


def extract_triples(chunk: Chunk) -> list[Triple]:
    """Ollama (Qwen3.5 4B) + few-shot 프롬프트로 Chunk에서 트리플 추출."""
    pass
