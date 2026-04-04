from datetime import datetime

from whatwasthat.models import SessionMeta, Turn
from whatwasthat.pipeline.chunker import chunk_turns


def _make_turns(contents: list[tuple[str, str]]) -> list[Turn]:
    return [Turn(role=r, content=c) for r, c in contents]


_LONG_USER = ("우리 프로젝트에서 DB는 PostgreSQL 대신 Kuzu를 선택했어. "
              "그래프 쿼리가 빨라서 임베딩은 ChromaDB로 저장하기로 했고. "
              "모델은 Qwen 3.5 4B를 사용하고, "
              "파이프라인은 파서-청커-추출기-저장소 순서로 구성했어.")
_LONG_ASST = ("좋은 선택입니다. Kuzu는 임베디드 그래프 DB라 설치 없이 사용 가능하고, "
              "ChromaDB는 벡터 검색에 최적화되어 있습니다. "
              "Qwen 3.5 4B는 한국어 지원이 괜찮고 "
              "4GB RAM이면 충분합니다. 파이프라인 구조도 합리적입니다.")


class TestChunkTurns:
    def test_single_topic_single_chunk(self):
        turns = _make_turns([
            ("user", _LONG_USER),
            ("assistant", _LONG_ASST),
            ("user", "그래 그렇게 하자. 모델은 Qwen 3.5 4B로 가자."),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert len(chunks) == 1
        assert len(chunks[0].turns) == 3

    def test_respects_max_turns(self):
        turns = _make_turns([
            ("user", f"기술 결정 메시지 번호 {i} — 이것은 충분히 긴 내용입니다") for i in range(15)
        ])
        chunks = chunk_turns(turns, session_id="s1", max_turns=5)
        assert all(len(c.turns) <= 5 for c in chunks)

    def test_empty_turns(self):
        chunks = chunk_turns([], session_id="s1")
        assert chunks == []

    def test_chunk_has_raw_text(self):
        turns = _make_turns([
            ("user", _LONG_USER),
            ("assistant", _LONG_ASST),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert "PostgreSQL" in chunks[0].raw_text

    def test_chunk_has_session_id(self):
        turns = _make_turns([
            ("user", _LONG_USER),
            ("assistant", _LONG_ASST),
        ])
        chunks = chunk_turns(turns, session_id="my-session")
        assert chunks[0].session_id == "my-session"

    def test_skips_chunks_without_user_turn(self):
        turns = _make_turns([
            ("assistant", _LONG_ASST),
            ("assistant", "계속 진행하겠습니다. 다음 단계를 확인합니다."),
        ])
        chunks = chunk_turns(turns, session_id="s1")
        assert len(chunks) == 0

    def test_skips_short_chunks(self):
        turns = _make_turns([("user", "응")])
        chunks = chunk_turns(turns, session_id="s1")
        assert len(chunks) == 0


class TestChunkMetadata:
    def test_chunk_receives_session_meta(self):
        meta = SessionMeta(session_id="s1", project="myproject",
                          project_path="/path/to/myproject", git_branch="feature/x",
                          started_at=datetime(2026, 4, 5))
        turns = _make_turns([("user", _LONG_USER), ("assistant", _LONG_ASST),
                            ("user", "그래 그렇게 하자. 모델은 Qwen 3.5 4B로 가자.")])
        chunks = chunk_turns(turns, session_id="s1", meta=meta)
        assert chunks[0].project == "myproject"
        assert chunks[0].git_branch == "feature/x"

    def test_chunk_works_without_meta(self):
        turns = _make_turns([("user", _LONG_USER), ("assistant", _LONG_ASST),
                            ("user", "그래 그렇게 하자.")])
        chunks = chunk_turns(turns, session_id="s1")
        assert chunks[0].project == ""
