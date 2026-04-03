"""트리플 추출 - Chunk에서 Knowledge Graph 트리플을 추출."""

import json
import re
import logging

import ollama

from whatwasthat.config import OLLAMA_MODEL
from whatwasthat.models import Chunk, Triple
from whatwasthat.pipeline.prompts import EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


def parse_llm_response(response_text: str) -> list[Triple]:
    """LLM 응답 텍스트를 Triple 리스트로 파싱."""
    cleaned = re.sub(r"```(?:json)?\s*", "", response_text).strip()
    cleaned = cleaned.rstrip("`").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM 응답 JSON 파싱 실패: %s", response_text[:200])
        return []

    triples: list[Triple] = []
    for item in data.get("triples", []):
        try:
            triples.append(Triple(
                subject=item["s"],
                subject_type=item["s_type"],
                predicate=item["p"],
                object=item["o"],
                object_type=item["o_type"],
                temporal=item.get("temporal"),
            ))
        except (KeyError, ValueError) as e:
            logger.warning("트리플 파싱 실패: %s — %s", item, e)
    return triples


def extract_triples(chunk: Chunk, model: str = OLLAMA_MODEL) -> list[Triple]:
    """Ollama로 Chunk에서 트리플 추출."""
    prompt = EXTRACTION_PROMPT.format(chunk_text=chunk.raw_text)
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_llm_response(response.message.content)
