"""extractor 모듈 테스트."""

from unittest.mock import MagicMock, patch

from whatwasthat.models import Chunk, Turn
from whatwasthat.pipeline.extractor import extract_triples, parse_llm_response


class TestParseLlmResponse:
    """LLM 응답 파싱 테스트 (Ollama 호출 없이)."""

    def test_parse_valid_json(self):
        response = (
            '{"triples": [{"s": "FastAPI", "s_type": "Framework",'
            ' "p": "CHOSEN_OVER", "o": "Flask", "o_type": "Framework",'
            ' "temporal": "decided"}]}'
        )
        triples = parse_llm_response(response)
        assert len(triples) == 1
        assert triples[0].subject == "FastAPI"
        assert triples[0].predicate == "CHOSEN_OVER"

    def test_parse_empty_triples(self):
        response = '{"triples": []}'
        triples = parse_llm_response(response)
        assert triples == []

    def test_parse_malformed_json(self):
        response = "이건 JSON이 아닙니다"
        triples = parse_llm_response(response)
        assert triples == []

    def test_parse_json_with_markdown_fence(self):
        response = (
            '```json\n{"triples": [{"s": "A", "s_type": "T",'
            ' "p": "R", "o": "B", "o_type": "T",'
            ' "temporal": null}]}\n```'
        )
        triples = parse_llm_response(response)
        assert len(triples) == 1


class TestExtractTriples:
    """Ollama 호출 모킹 테스트."""

    def test_extract_calls_ollama(self):
        chunk = Chunk(
            id="c1", session_id="s1",
            turns=[Turn(role="user", content="FastAPI로 하자")],
            raw_text="[user]: FastAPI로 하자",
        )
        mock_response = MagicMock()
        mock_response.message.content = (
            '{"triples": [{"s": "FastAPI", "s_type": "Framework",'
            ' "p": "SELECTED", "o": "프로젝트", "o_type": "Project",'
            ' "temporal": "decided"}]}'
        )

        with patch("whatwasthat.pipeline.extractor.ollama") as mock_ollama:
            mock_ollama.chat.return_value = mock_response
            triples = extract_triples(chunk)
            assert len(triples) == 1
            mock_ollama.chat.assert_called_once()
