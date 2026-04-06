"""CodexCliParser + detect_parser Codex 감지 테스트."""
from pathlib import Path
from whatwasthat.pipeline.parser import CodexCliParser, detect_parser

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestCodexCliParser:
    def test_source_name(self):
        assert CodexCliParser().source == "codex-cli"

    def test_can_parse_rollout(self):
        assert CodexCliParser().can_parse(FIXTURES / "codex_rollout.jsonl") is True

    def test_cannot_parse_claude_jsonl(self, tmp_path):
        f = tmp_path / "claude.jsonl"
        f.write_text('{"type":"user","message":{"role":"user","content":"hi"},"sessionId":"s1"}\n')
        assert CodexCliParser().can_parse(f) is False

    def test_cannot_parse_gemini_json(self):
        assert CodexCliParser().can_parse(FIXTURES / "gemini_session.json") is False

    def test_parse_turns_extracts_user_and_agent(self):
        parser = CodexCliParser()
        turns = parser.parse_turns(FIXTURES / "codex_rollout.jsonl")
        assert len(turns) == 4
        assert turns[0].role == "user"
        assert turns[1].role == "assistant"
        assert turns[0].source == "codex-cli"
        assert "로그인" in turns[0].content

    def test_parse_turns_has_timestamps(self):
        parser = CodexCliParser()
        turns = parser.parse_turns(FIXTURES / "codex_rollout.jsonl")
        assert turns[0].timestamp is not None

    def test_parse_meta(self):
        parser = CodexCliParser()
        meta = parser.parse_meta(FIXTURES / "codex_rollout.jsonl")
        assert meta is not None
        assert meta.session_id == "codex-001"
        assert meta.source == "codex-cli"
        assert meta.project == "myapp"
        assert meta.git_branch == "main"
        assert meta.project_path == "/Users/hyuk/projects/myapp"

    def test_parse_meta_turn_count(self):
        parser = CodexCliParser()
        meta = parser.parse_meta(FIXTURES / "codex_rollout.jsonl")
        assert meta is not None
        assert meta.turn_count == 4


class TestDetectCodex:
    def test_detects_codex_rollout(self):
        parser = detect_parser(FIXTURES / "codex_rollout.jsonl")
        assert parser is not None
        assert parser.source == "codex-cli"
