"""트리플 추출 - Chunk에서 Knowledge Graph 트리플을 추출 (Triplex 모델)."""

import json
import logging
import re

import ollama

from whatwasthat.config import OLLAMA_MODEL
from whatwasthat.models import Chunk, Triple
from whatwasthat.pipeline.prompts import ENTITY_TYPES, PREDICATES, TRIPLEX_PROMPT

logger = logging.getLogger(__name__)


def _clean_response(response_text: str) -> str:
    """LLM 응답에서 JSON만 추출."""
    text = response_text.strip()
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.rstrip("`").strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return match.group(0)
    return text


def _parse_triplex_entry(entry: str) -> dict[str, str] | None:
    """Triplex 엔트리 한 줄을 파싱.

    엔티티: '[1], TECHNOLOGY:FastAPI' → {'id': '1', 'type': 'Technology', 'name': 'FastAPI'}
    트리플: '[1] CHOSEN_OVER [2]'
      → {'subject_id': '1', 'predicate': 'CHOSEN_OVER', 'object_id': '2'}
    """
    entry = entry.strip()
    # 트리플 패턴: [N] PREDICATE [M]
    triple_match = re.match(r"\[(\d+)\]\s+(\w+)\s+\[(\d+)\]", entry)
    if triple_match:
        return {
            "kind": "triple",
            "subject_id": triple_match.group(1),
            "predicate": triple_match.group(2),
            "object_id": triple_match.group(3),
        }
    # 엔티티 패턴: [N], TYPE:NAME
    entity_match = re.match(r"\[(\d+)\],?\s*(\w+):(.+)", entry)
    if entity_match:
        return {
            "kind": "entity",
            "id": entity_match.group(1),
            "type": entity_match.group(2).strip(),
            "name": entity_match.group(3).strip(),
        }
    return None


def parse_llm_response(response_text: str) -> list[Triple]:
    """Triplex 응답을 Triple 리스트로 파싱."""
    cleaned = _clean_response(response_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM 응답 JSON 파싱 실패: %s", response_text[:300])
        return []

    entries = data.get("entities_and_triples", [])
    if not entries:
        return []

    # 1단계: 엔티티 맵 구축
    entity_map: dict[str, dict[str, str]] = {}
    raw_triples: list[dict[str, str]] = []

    for entry in entries:
        if not isinstance(entry, str):
            continue
        parsed = _parse_triplex_entry(entry)
        if not parsed:
            continue
        if parsed["kind"] == "entity":
            entity_map[parsed["id"]] = {
                "name": parsed["name"],
                "type": parsed["type"],
            }
        elif parsed["kind"] == "triple":
            raw_triples.append(parsed)

    # 2단계: 트리플 조립
    triples: list[Triple] = []
    for rt in raw_triples:
        subj = entity_map.get(rt["subject_id"])
        obj = entity_map.get(rt["object_id"])
        if not subj or not obj:
            logger.warning("엔티티 참조 누락: %s", rt)
            continue
        triples.append(Triple(
            subject=subj["name"],
            subject_type=subj["type"],
            predicate=rt["predicate"],
            object=obj["name"],
            object_type=obj["type"],
        ))
    return triples


def extract_triples(chunk: Chunk, model: str = OLLAMA_MODEL) -> list[Triple]:
    """Triplex로 Chunk에서 트리플 추출."""
    prompt = TRIPLEX_PROMPT.format(
        entity_types=json.dumps(ENTITY_TYPES),
        predicates=json.dumps(PREDICATES),
        chunk_text=chunk.raw_text,
    )
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
    )
    return parse_llm_response(response.message.content)
