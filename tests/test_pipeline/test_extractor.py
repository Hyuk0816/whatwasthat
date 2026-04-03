"""extractor 모듈 테스트."""

from unittest.mock import MagicMock, patch

from whatwasthat.models import Chunk, Turn
from whatwasthat.pipeline.extractor import extract_triples, parse_llm_response

SAMPLE_RESPONSE = (
    '{"triples": [{"s": "FastAPI", "s_type": "Framework",'
    ' "p": "CHOSEN_OVER", "o": "Flask", "o_type": "Framework"},'
    ' {"s": "FastAPI", "s_type": "Framework",'
    ' "p": "HAS_ADVANTAGE", "o": "async support",'
    ' "o_type": "Feature"}]}'
)


class TestParseLlmResponse:
    def test_parse_valid_json(self):
        triples = parse_llm_response(SAMPLE_RESPONSE)
        assert len(triples) == 2
        assert triples[0].subject == "FastAPI"
        assert triples[0].predicate == "CHOSEN_OVER"
        assert triples[0].object == "Flask"

    def test_parse_empty_triples(self):
        assert parse_llm_response('{"triples": []}') == []

    def test_parse_malformed_json(self):
        assert parse_llm_response("not json") == []

    def test_parse_with_markdown_fence(self):
        response = f"```json\n{SAMPLE_RESPONSE}\n```"
        triples = parse_llm_response(response)
        assert len(triples) == 2

    def test_parse_with_think_tags(self):
        response = f"<think>reasoning</think>{SAMPLE_RESPONSE}"
        triples = parse_llm_response(response)
        assert len(triples) == 2

    def test_parse_missing_key_skips(self):
        response = '{"triples": [{"s": "A", "p": "R"}]}'
        triples = parse_llm_response(response)
        assert triples == []


class TestExtractTriples:
    def test_extract_calls_ollama(self):
        chunk = Chunk(
            id="c1",
            session_id="s1",
            turns=[Turn(role="user", content="FastAPI로 하자")],
            raw_text="[user]: FastAPI로 하자",
        )
        mock_response = MagicMock()
        mock_response.message.content = SAMPLE_RESPONSE

        with patch("whatwasthat.pipeline.extractor.ollama") as mock_ollama:
            mock_ollama.chat.return_value = mock_response
            triples = extract_triples(chunk)
            assert len(triples) == 2
            mock_ollama.chat.assert_called_once()
