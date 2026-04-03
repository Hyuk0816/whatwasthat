"""extractor 모듈 테스트 (Triplex 포맷)."""

from unittest.mock import MagicMock, patch

from whatwasthat.models import Chunk, Turn
from whatwasthat.pipeline.extractor import extract_triples, parse_llm_response

TRIPLEX_RESPONSE = (
    '{"entities_and_triples": ['
    '"[1], TECHNOLOGY:FastAPI", "[2], TECHNOLOGY:Flask",'
    ' "[1] CHOSEN_OVER [2]", "[3], FEATURE:async support",'
    ' "[1] HAS_ADVANTAGE [3]"]}'
)


class TestParseLlmResponse:
    """Triplex 응답 파싱 테스트."""

    def test_parse_triplex_format(self):
        triples = parse_llm_response(TRIPLEX_RESPONSE)
        assert len(triples) == 2
        assert triples[0].subject == "FastAPI"
        assert triples[0].predicate == "CHOSEN_OVER"
        assert triples[0].object == "Flask"

    def test_parse_entity_types(self):
        triples = parse_llm_response(TRIPLEX_RESPONSE)
        assert triples[0].subject_type == "TECHNOLOGY"
        assert triples[1].object_type == "FEATURE"

    def test_parse_empty_entries(self):
        response = '{"entities_and_triples": []}'
        triples = parse_llm_response(response)
        assert triples == []

    def test_parse_malformed_json(self):
        response = "이건 JSON이 아닙니다"
        triples = parse_llm_response(response)
        assert triples == []

    def test_parse_with_markdown_fence(self):
        response = f"```json\n{TRIPLEX_RESPONSE}\n```"
        triples = parse_llm_response(response)
        assert len(triples) == 2

    def test_missing_entity_reference(self):
        response = '{"entities_and_triples": ["[1], TECHNOLOGY:FastAPI", "[1] USES [99]"]}'
        triples = parse_llm_response(response)
        assert triples == []


class TestExtractTriples:
    """Ollama 호출 모킹 테스트."""

    def test_extract_calls_ollama(self):
        chunk = Chunk(
            id="c1", session_id="s1",
            turns=[Turn(role="user", content="FastAPI로 하자")],
            raw_text="[user]: FastAPI로 하자",
        )
        mock_response = MagicMock()
        mock_response.message.content = TRIPLEX_RESPONSE

        with patch("whatwasthat.pipeline.extractor.ollama") as mock_ollama:
            mock_ollama.chat.return_value = mock_response
            triples = extract_triples(chunk)
            assert len(triples) == 2
            mock_ollama.chat.assert_called_once()
