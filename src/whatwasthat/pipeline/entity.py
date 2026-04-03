"""엔티티 해소 - 새 엔티티가 기존 노드와 동일한지 판단."""

import re

from whatwasthat.models import Entity


def _normalize(name: str) -> str:
    """엔티티명 정규화: 소문자, 공백/특수문자 제거."""
    return re.sub(r"[\s\-_\.]+", "", name.lower())


def resolve_entity(new_name: str, existing_entities: list[Entity]) -> Entity | None:
    """새 엔티티명이 기존 엔티티와 동일한지 판단.

    PoC: 정규화 매칭만. Phase 3: 임베딩 유사도, LLM 폴백 추가.
    """
    normalized_new = _normalize(new_name)

    for entity in existing_entities:
        if _normalize(entity.name) == normalized_new:
            return entity
        for alias in entity.aliases:
            if _normalize(alias) == normalized_new:
                return entity

    return None
