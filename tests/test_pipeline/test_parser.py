from pathlib import Path

from whatwasthat.pipeline.parser import parse_jsonl
from whatwasthat.models import Turn

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestParseJsonl:
    def test_parse_extracts_user_and_assistant_turns(self):
        turns = parse_jsonl(FIXTURES / "sample_session.jsonl")
        assert len(turns) == 4  # user, assistant, user, assistant (system/permission 제외)
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
