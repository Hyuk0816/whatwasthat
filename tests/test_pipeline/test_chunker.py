from whatwasthat.models import Turn
from whatwasthat.pipeline.chunker import chunk_turns


def _make_turns(contents: list[tuple[str, str]]) -> list[Turn]:
    return [Turn(role=r, content=c) for r, c in contents]


class TestChunkTurns:
    def test_single_topic_single_chunk(self):
        turns = _make_turns([
            ("user", "FastAPI 대신 Flask 쓰자"),
            ("assistant", "FastAPI가 async 지원이 좋습니다"),
            ("user", "그래 FastAPI로 하자"),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert len(chunks) == 1
        assert len(chunks[0].turns) == 3

    def test_respects_max_turns(self):
        turns = _make_turns([
            ("user", f"메시지 {i}") for i in range(15)
        ])
        chunks = chunk_turns(turns, session_id="s1", max_turns=5)
        assert all(len(c.turns) <= 5 for c in chunks)

    def test_empty_turns(self):
        chunks = chunk_turns([], session_id="s1")
        assert chunks == []

    def test_chunk_has_raw_text(self):
        turns = _make_turns([
            ("user", "DB를 PostgreSQL로 하자"),
            ("assistant", "좋습니다"),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert "PostgreSQL" in chunks[0].raw_text

    def test_chunk_has_session_id(self):
        turns = _make_turns([("user", "테스트")])
        chunks = chunk_turns(turns, session_id="my-session")
        assert chunks[0].session_id == "my-session"
