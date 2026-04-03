"""엔티티 해소 - 새 엔티티가 기존 노드와 동일한지 판단."""

from whatwasthat.models import Entity


def resolve_entity(new_name: str, existing_entities: list[Entity]) -> Entity | None:
    """새 엔티티명이 기존 엔티티와 동일한지 판단.

    1차: 정규화 매칭 (소문자, 공백 제거 등)
    2차: 임베딩 유사도
    3차: LLM (최후수단)
    """
    pass
