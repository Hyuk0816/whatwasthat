from pathlib import Path

from whatwasthat.models import Turn
from whatwasthat.pipeline.parser import parse_jsonl, parse_session_meta

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestParseJsonl:
    def test_parse_extracts_user_and_assistant_turns(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        # user, assistant, user (마지막 assistant는 짧은 상태 메시지라 필터됨)
        assert len(turns) == 3
        assert turns[0].role == "user"
        assert turns[0].content == "FastAPI 대신 Flask 쓰자"

    def test_parse_filters_non_text_content(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        # assistant 응답에서 thinking, tool_use 제외하고 text만 추출
        assert "생각 중" not in turns[1].content
        assert "async 지원" in turns[1].content

    def test_parse_handles_list_content(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        # content가 리스트인 user 메시지도 text 추출
        assert turns[2].content == "그래 FastAPI로 하자"

    def test_parse_empty_file(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        turns = parse_jsonl(empty)
        assert turns == []

    def test_parse_returns_turn_instances(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        assert all(isinstance(t, Turn) for t in turns)


class TestParseSessionMeta:
    def test_extracts_session_meta(self):
        meta = parse_session_meta(FIXTURES / "sample_session.jsonl")
        assert meta is not None
        assert meta.session_id == "test-session-001"
        assert meta.project == "TestProject"
        assert meta.git_branch == "main"

    def test_meta_from_empty_file(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert parse_session_meta(empty) is None
