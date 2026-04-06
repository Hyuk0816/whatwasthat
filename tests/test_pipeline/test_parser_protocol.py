"""SessionParser Protocol + ClaudeCodeParser + detect_parser 테스트."""

from pathlib import Path

from whatwasthat.pipeline.parser import ClaudeCodeParser, detect_parser

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestClaudeCodeParser:
    def test_source_name(self):
        parser = ClaudeCodeParser()
        assert parser.source == "claude-code"

    def test_can_parse_jsonl(self):
        parser = ClaudeCodeParser()
        assert parser.can_parse(FIXTURES / "sample_session.jsonl") is True

    def test_cannot_parse_non_jsonl(self, tmp_path):
        f = tmp_path / "session.json"
        f.write_text('{"contents":[{"role":"user","parts":[{"text":"hi"}]}]}')
        parser = ClaudeCodeParser()
        assert parser.can_parse(f) is False

    def test_parse_turns_delegates(self):
        parser = ClaudeCodeParser()
        turns = parser.parse_turns(FIXTURES / "sample_session.jsonl")
        assert len(turns) >= 1
        assert all(t.source == "claude-code" for t in turns)

    def test_parse_meta_delegates(self):
        parser = ClaudeCodeParser()
        meta = parser.parse_meta(FIXTURES / "sample_session.jsonl")
        assert meta is not None
        assert meta.source == "claude-code"
        assert meta.session_id == "test-session-001"

    def test_discover_sessions(self):
        parser = ClaudeCodeParser()
        sessions = parser.discover_sessions(FIXTURES)
        assert "sample_session" in sessions


class TestDetectParser:
    def test_detects_claude_code(self):
        parser = detect_parser(FIXTURES / "sample_session.jsonl")
        assert parser is not None
        assert parser.source == "claude-code"

    def test_returns_none_for_unknown(self, tmp_path):
        f = tmp_path / "unknown.txt"
        f.write_text("just plain text")
        assert detect_parser(f) is None


class TestIngestWithDetectParser:
    def test_ingest_gemini_json_end_to_end(self):
        """Gemini JSON 파일을 detect_parser -> parse -> chunk 전체 플로우 테스트."""
        from whatwasthat.pipeline.chunker import chunk_turns

        fixture = FIXTURES / "gemini_session.json"
        parser = detect_parser(fixture)
        assert parser is not None

        turns = parser.parse_turns(fixture)
        meta = parser.parse_meta(fixture)
        chunks = chunk_turns(turns, session_id="gem-test", meta=meta)

        if chunks:
            assert chunks[0].source == "gemini-cli"

    def test_ingest_claude_jsonl_end_to_end(self):
        """Claude Code JSONL도 detect_parser로 동일하게 처리."""
        from whatwasthat.pipeline.chunker import chunk_turns

        fixture = FIXTURES / "sample_session.jsonl"
        parser = detect_parser(fixture)
        assert parser is not None
        assert parser.source == "claude-code"

        turns = parser.parse_turns(fixture)
        meta = parser.parse_meta(fixture)
        chunks = chunk_turns(turns, session_id="claude-test", meta=meta)
        if chunks:
            assert chunks[0].source == "claude-code"
