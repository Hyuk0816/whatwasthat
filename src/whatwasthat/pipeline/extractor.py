"""트리플 추출 - Chunk에서 Knowledge Graph 트리플을 추출."""

import json
import logging
import re

import ollama

from whatwasthat.config import OLLAMA_MODEL
from whatwasthat.models import Chunk, Triple
from whatwasthat.pipeline.prompts import SYSTEM_PROMPT, USER_PROMPT

logger = logging.getLogger(__name__)


def _clean_response(response_text: str) -> str:
    """LLM 응답에서 JSON만 추출."""
    text = response_text.strip()
    # <think>...</think> 태그 제거
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # 마크다운 코드 펜스 제거
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.rstrip("`").strip()
    # JSON 객체 부분만 추출 (첫 { 부터 마지막 } 까지)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return match.group(0)
    return text


def parse_llm_response(response_text: str) -> list[Triple]:
    """LLM 응답 텍스트를 Triple 리스트로 파싱."""
    cleaned = _clean_response(response_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM 응답 JSON 파싱 실패: %s", response_text[:300])
        return []

    triples: list[Triple] = []

    # 우리 스키마: {"triples": [{"s":..., "p":..., "o":...}]}
    raw_triples = data.get("triples", [])

    for item in raw_triples:
        try:
            triples.append(Triple(
                subject=item["s"],
                subject_type=item.get("s_type", "Unknown"),
                predicate=item["p"],
                object=item["o"],
                object_type=item.get("o_type", "Unknown"),
                temporal=item.get("temporal"),
            ))
        except (KeyError, ValueError) as e:
            logger.warning("트리플 파싱 실패: %s — %s", item, e)
    return triples


def extract_triples(chunk: Chunk, model: str = OLLAMA_MODEL) -> list[Triple]:
    """Ollama로 Chunk에서 트리플 추출."""
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT.format(chunk_text=chunk.raw_text)},
        ],
        format="json",
    )
    return parse_llm_response(response.message.content)
