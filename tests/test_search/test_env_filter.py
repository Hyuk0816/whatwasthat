"""env 메타데이터 전파 및 검색 필터 회귀 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

from whatwasthat.models import SessionMeta, Turn
from whatwasthat.pipeline.chunker import chunk_turns
from whatwasthat.search.engine import SearchEngine
from whatwasthat.storage.vector import VectorStore


def _long_text(marker: str) -> str:
    return f"{marker} " + ("padding text " * 30)


def test_chunk_turns_propagates_env_from_session_meta():
    turns = [
        Turn(role="user", content=_long_text("redis decision")),
        Turn(role="assistant", content=_long_text("redis answer")),
    ]
    meta = SessionMeta(
        session_id="s1",
        project="proj",
        project_path="/tmp/proj",
        git_branch="main",
        started_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
        env="staging",
    )

    _spans, chunks = chunk_turns(turns, session_id="s1", meta=meta)

    assert chunks
    assert all(chunk.env == "staging" for chunk in chunks)


def test_search_filters_by_env_and_returns_env_on_results(tmp_data_dir):
    store = VectorStore(tmp_data_dir / "vector")
    store.initialize()

    prod_turns = [Turn(role="user", content=_long_text("redis production setup"))]
    dev_turns = [Turn(role="user", content=_long_text("redis development setup"))]

    _prod_spans, prod_chunks = chunk_turns(
        prod_turns,
        session_id="s_prod",
        min_turns=1,
        meta=SessionMeta(
            session_id="s_prod",
            project="proj",
            project_path="/tmp/proj",
            git_branch="main",
            started_at=datetime(2026, 4, 8, 1, tzinfo=timezone.utc),
            env="prod",
        ),
    )
    _dev_spans, dev_chunks = chunk_turns(
        dev_turns,
        session_id="s_dev",
        min_turns=1,
        meta=SessionMeta(
            session_id="s_dev",
            project="proj",
            project_path="/tmp/proj",
            git_branch="main",
            started_at=datetime(2026, 4, 8, 2, tzinfo=timezone.utc),
            env="dev",
        ),
    )
    store.upsert_chunks(prod_chunks + dev_chunks)

    engine = SearchEngine(vector=store)
    results = engine.search("redis setup", env="prod")

    assert results
    assert {result.session_id for result in results} == {"s_prod"}
    assert all(result.env == "prod" for result in results)
    assert all(chunk.env == "prod" for result in results for chunk in result.chunks)
