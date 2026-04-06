"""GeminiCliParser + detect_parser Gemini 감지 테스트."""

from pathlib import Path

from whatwasthat.pipeline.parser import GeminiCliParser, detect_parser

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestGeminiCliParser:
    def test_source_name(self):
        assert GeminiCliParser().source == "gemini-cli"

    def test_can_parse_json(self):
        assert GeminiCliParser().can_parse(FIXTURES / "gemini_session.json") is True

    def test_can_parse_jsonl(self):
        assert GeminiCliParser().can_parse(FIXTURES / "gemini_session.jsonl") is True

    def test_cannot_parse_claude_jsonl(self, tmp_path):
        f = tmp_path / "claude.jsonl"
        f.write_text('{"type":"user","message":{"role":"user","content":"hi"},"sessionId":"s1"}\n')
        assert GeminiCliParser().can_parse(f) is False

    def test_parse_json_extracts_text_turns_only(self):
        parser = GeminiCliParser()
        turns = parser.parse_turns(FIXTURES / "gemini_session.json")
        # "info" 타입은 제외, user + gemini 타입만 추출
        # user: "src/main.ts 파일 읽어줘", gemini: "이 파일은 엔트리포인트...",
        # user: "TypeScript로 변환해줘", gemini: "TypeScript로 변환하겠습니다..."
        assert len(turns) == 4
        assert turns[0].role == "user"
        assert turns[1].role == "assistant"  # "gemini" → "assistant" 정규화
        assert turns[0].source == "gemini-cli"

    def test_parse_jsonl_format(self):
        parser = GeminiCliParser()
        turns = parser.parse_turns(FIXTURES / "gemini_session.jsonl")
        assert len(turns) == 4
        assert turns[1].role == "assistant"  # "gemini" → "assistant" 정규화

    def test_parse_meta_json(self):
        parser = GeminiCliParser()
        meta = parser.parse_meta(FIXTURES / "gemini_session.json")
        assert meta is not None
        assert meta.source == "gemini-cli"
        assert meta.session_id == "gem-json-001"

    def test_parse_meta_jsonl(self):
        parser = GeminiCliParser()
        meta = parser.parse_meta(FIXTURES / "gemini_session.jsonl")
        assert meta is not None
        assert meta.session_id == "gem-001"
        assert meta.source == "gemini-cli"


class TestDetectGemini:
    def test_detects_gemini_json(self):
        parser = detect_parser(FIXTURES / "gemini_session.json")
        assert parser is not None
        assert parser.source == "gemini-cli"

    def test_detects_gemini_jsonl(self):
        parser = detect_parser(FIXTURES / "gemini_session.jsonl")
        assert parser is not None
        assert parser.source == "gemini-cli"
