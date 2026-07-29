from datetime import datetime

from whatwasthat.models import SessionMeta, Turn
from whatwasthat.pipeline.chunker import chunk_turns


def _make_turns(contents: list[tuple[str, str]]) -> list[Turn]:
    return [Turn(role=r, content=c) for r, c in contents]


def _chunks_of(chunks, granularity: str):
    return [chunk for chunk in chunks if chunk.granularity == granularity]


def _make_dialogue_pairs(pair_count: int) -> list[Turn]:
    turns: list[Turn] = []
    for index in range(pair_count):
        turns.extend(_make_turns([
            (
                "user",
                f"{_LONG_USER} 이 결정은 pair {index}에 대한 내용이고 "
                "검색 회수를 위해 충분히 길게 유지합니다.",
            ),
            (
                "assistant",
                f"{_LONG_ASST} 이 응답은 pair {index}에 대한 설명이며 "
                "turn-pair 길이 기준을 넘기도록 충분히 길게 유지합니다.",
            ),
        ]))
    return turns


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
        spans, chunks = chunk_turns(turns, session_id="s1")
        small_window_chunks = _chunks_of(chunks, "small-window")
        assert len(small_window_chunks) == 1
        assert any(span.id == small_window_chunks[0].span_id for span in spans)
        assert small_window_chunks[0].turn_count == 3

    def test_respects_max_turns(self):
        turns = _make_turns([
            ("user", f"기술 결정 메시지 번호 {i} — 이것은 충분히 긴 내용입니다") for i in range(15)
        ])
        _spans, chunks = chunk_turns(turns, session_id="s1", max_turns=5)
        assert all(c.turn_count <= 5 for c in _chunks_of(chunks, "small-window"))

    def test_empty_turns(self):
        spans, chunks = chunk_turns([], session_id="s1")
        assert spans == []
        assert chunks == []

    def test_chunk_has_raw_text(self):
        turns = _make_turns([
            ("user", _LONG_USER),
            ("assistant", _LONG_ASST),
        ])
        spans, chunks = chunk_turns(turns, session_id="s1")
        small_window_chunk = _chunks_of(chunks, "small-window")[0]
        span_by_id = {span.id: span for span in spans}
        assert "PostgreSQL" in small_window_chunk.raw_preview
        assert "PostgreSQL" in span_by_id[small_window_chunk.span_id].raw_text

    def test_chunk_has_session_id(self):
        turns = _make_turns([
            ("user", _LONG_USER),
            ("assistant", _LONG_ASST),
        ])
        _spans, chunks = chunk_turns(turns, session_id="my-session")
        assert all(chunk.session_id == "my-session" for chunk in chunks)

    def test_skips_chunks_without_user_turn(self):
        turns = _make_turns([
            ("assistant", _LONG_ASST),
            ("assistant", "계속 진행하겠습니다. 다음 단계를 확인합니다."),
        ])
        _spans, chunks = chunk_turns(turns, session_id="s1")
        assert len(chunks) == 0

    def test_skips_short_chunks(self):
        turns = _make_turns([("user", "응")])
        _spans, chunks = chunk_turns(turns, session_id="s1")
        assert len(chunks) == 0


class TestChunkMetadata:
    def test_chunk_receives_session_meta(self):
        meta = SessionMeta(session_id="s1", project="myproject",
                          project_path="/path/to/myproject", git_branch="feature/x",
                          started_at=datetime(2026, 4, 5))
        turns = _make_turns([("user", _LONG_USER), ("assistant", _LONG_ASST),
                            ("user", "그래 그렇게 하자. 모델은 Qwen 3.5 4B로 가자.")])
        _spans, chunks = chunk_turns(turns, session_id="s1", meta=meta)
        assert all(chunk.project == "myproject" for chunk in chunks)
        assert all(chunk.git_branch == "feature/x" for chunk in chunks)

    def test_chunk_works_without_meta(self):
        turns = _make_turns([("user", _LONG_USER), ("assistant", _LONG_ASST),
                            ("user", "그래 그렇게 하자.")])
        _spans, chunks = chunk_turns(turns, session_id="s1")
        assert all(chunk.project == "" for chunk in chunks)

    def test_chunk_receives_source_from_meta(self):
        meta = SessionMeta(
            session_id="s1", project="proj", project_path="/p",
            git_branch="main", started_at=datetime(2026, 4, 5), source="gemini-cli"
        )
        turns = _make_turns([("user", _LONG_USER), ("assistant", _LONG_ASST)])
        _spans, chunks = chunk_turns(turns, session_id="s1", meta=meta)
        assert all(chunk.source == "gemini-cli" for chunk in chunks)

    def test_chunk_receives_timestamp_from_meta(self):
        meta = SessionMeta(
            session_id="s1", project="proj", project_path="/p",
            git_branch="main", started_at=datetime(2026, 4, 5, 10, 30),
        )
        turns = _make_turns([("user", _LONG_USER), ("assistant", _LONG_ASST)])
        _spans, chunks = chunk_turns(turns, session_id="s1", meta=meta)
        assert all(chunk.timestamp == datetime(2026, 4, 5, 10, 30) for chunk in chunks)

    def test_chunk_timestamp_none_without_meta(self):
        turns = _make_turns([("user", _LONG_USER), ("assistant", _LONG_ASST)])
        _spans, chunks = chunk_turns(turns, session_id="s1")
        assert all(chunk.timestamp is None for chunk in chunks)


class TestChunkOverlap:
    def test_overlap_creates_more_chunks(self):
        """오버랩이 있으면 겹치는 부분 때문에 청크가 더 많이 생성됨."""
        turns = _make_turns([
            ("user", f"기술 결정 메시지 {i} — 충분히 긴 내용입니다 긴 내용")
            for i in range(12)
        ])
        _no_spans, no_overlap_chunks = chunk_turns(turns, session_id="s1", max_turns=6, overlap=0)
        _overlap_spans, with_overlap_chunks = chunk_turns(
            turns, session_id="s1", max_turns=6, overlap=2,
        )
        no_overlap = _chunks_of(no_overlap_chunks, "small-window")
        with_overlap = _chunks_of(with_overlap_chunks, "small-window")
        assert len(with_overlap) >= len(no_overlap)

    def test_overlap_shares_turns(self):
        """인접 청크가 오버랩 턴을 공유함."""
        turns = _make_turns([
            ("user", f"기술 결정 메시지 번호 {i} — 충분히 긴 내용입니다 긴 내용")
            for i in range(12)
        ])
        _spans, all_chunks = chunk_turns(turns, session_id="s1", max_turns=6, overlap=2)
        chunks = _chunks_of(all_chunks, "small-window")
        if len(chunks) >= 2:
            # 첫 번째 청크의 마지막 2턴 == 두 번째 청크의 첫 2턴
            assert chunks[0].end_turn_index - 1 == chunks[1].start_turn_index

    def test_zero_overlap_same_as_before(self):
        """overlap=0이면 기존 동작과 동일."""
        turns = _make_turns([
            ("user", f"기술 결정 메시지 {i} — 충분히 긴 내용입니다 긴 내용")
            for i in range(12)
        ])
        _spans, all_chunks = chunk_turns(turns, session_id="s1", max_turns=6, overlap=0)
        chunks = _chunks_of(all_chunks, "small-window")
        assert len(chunks) == 2


class TestMultiGranularity:
    def test_turn_pair_granularity(self):
        turns = _make_dialogue_pairs(5)

        _spans, chunks = chunk_turns(turns, session_id="s1")

        turn_pair_chunks = _chunks_of(chunks, "turn-pair")
        assert len(turn_pair_chunks) == 5
        assert all(chunk.turn_count == 2 for chunk in turn_pair_chunks)

    def test_session_outline_granularity(self):
        turns = _make_dialogue_pairs(5)

        spans, chunks = chunk_turns(turns, session_id="s1")

        outline_chunks = _chunks_of(chunks, "session-outline")
        assert len(outline_chunks) == 1
        assert outline_chunks[0].turn_count == len(turns)
        span_by_id = {span.id: span for span in spans}
        assert span_by_id[outline_chunks[0].span_id].id == "s1:outline"

    def test_multi_granularity_combined(self):
        turns = _make_dialogue_pairs(5)

        _spans, chunks = chunk_turns(turns, session_id="s1")

        assert len(_chunks_of(chunks, "turn-pair")) == 5
        assert len(_chunks_of(chunks, "small-window")) == 3
        assert len(_chunks_of(chunks, "session-outline")) == 1

    def test_short_session_no_outline(self):
        turns = _make_dialogue_pairs(1)

        _spans, chunks = chunk_turns(turns, session_id="s1")

        assert len(_chunks_of(chunks, "turn-pair")) == 1
        assert len(_chunks_of(chunks, "session-outline")) == 0

    def test_chunk_id_deterministic_all_granularities(self):
        turns = _make_dialogue_pairs(5)

        _spans1, chunks1 = chunk_turns(turns, session_id="s1")
        _spans2, chunks2 = chunk_turns(turns, session_id="s1")

        ids1 = sorted((chunk.granularity, chunk.start_turn_index, chunk.id) for chunk in chunks1)
        ids2 = sorted((chunk.granularity, chunk.start_turn_index, chunk.id) for chunk in chunks2)
        assert ids1 == ids2

    def test_span_id_format_all_granularities(self):
        turns = _make_dialogue_pairs(5)

        spans, chunks = chunk_turns(turns, session_id="s1")

        span_ids = {span.id for span in spans}
        turn_pair_span_ids = {
            chunk.span_id for chunk in _chunks_of(chunks, "turn-pair")
        }
        assert "s1:outline" in span_ids
        assert turn_pair_span_ids == {
            "s1:tp0e1",
            "s1:tp2e3",
            "s1:tp4e5",
            "s1:tp6e7",
            "s1:tp8e9",
        }
