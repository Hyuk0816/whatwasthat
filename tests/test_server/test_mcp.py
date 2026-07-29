"""MCP 서버 테스트."""

import pytest

from whatwasthat.server.mcp import mcp


class TestMcpServer:
    def test_server_has_tools(self):
        tools = list(mcp._tool_manager._tools.keys())
        assert "search_memory" in tools
        assert "search_all" in tools
        assert "recall_chunk" in tools
        assert "ingest_session" in tools

    def test_server_name(self):
        assert mcp.name == "whatwasthat"

    @pytest.mark.asyncio
    async def test_search_memory_empty_db(self, tmp_data_dir, monkeypatch):
        from whatwasthat import config
        monkeypatch.setattr(config, "CHROMA_DB_PATH", tmp_data_dir / "vector")
        monkeypatch.setattr(config, "WWT_DATA_DIR", tmp_data_dir)

        from whatwasthat.server.mcp import search_memory
        result = search_memory(query="아무거나", project=None, cwd=None)
        assert "찾지 못했습니다" in result

    @pytest.mark.asyncio
    async def test_search_memory_with_cwd(self, tmp_data_dir, monkeypatch):
        from whatwasthat import config
        monkeypatch.setattr(config, "CHROMA_DB_PATH", tmp_data_dir / "vector")
        monkeypatch.setattr(config, "WWT_DATA_DIR", tmp_data_dir)

        from whatwasthat.server.mcp import search_memory
        result = search_memory(
            query="DB 선택",
            project=None,
            cwd="/Users/hyuk/PycharmProjects/whatwasthat",
        )
        # 빈 DB라 결과 없음, 하지만 에러 없이 동작
        assert isinstance(result, str)

    def test_get_engine_returns_singleton(self):
        """_get_engine()이 같은 인스턴스를 반환."""
        from whatwasthat.server.mcp import _get_engine, _reset_engine
        _reset_engine()
        engine1 = _get_engine()
        engine2 = _get_engine()
        assert engine1 is engine2
        _reset_engine()  # cleanup

    def test_write_lock_creates_lock_file(self, tmp_data_dir, monkeypatch):
        from whatwasthat import config
        monkeypatch.setattr(config, "CHROMA_DB_PATH", tmp_data_dir / "vector")
        monkeypatch.setattr(config, "WWT_DATA_DIR", tmp_data_dir)

        from whatwasthat.server.mcp import _write_lock
        lock_path = tmp_data_dir / "wwt.lock"
        with _write_lock():
            assert lock_path.exists()
        assert lock_path.exists()

    def test_search_memory_uses_routing(self, tmp_data_dir, monkeypatch):
        """search_memory는 내부적으로 search_with_routing을 호출해야 한다.

        projA로 요청하지만 frontend 프로젝트에 있는 내용이
        라우팅 확장으로 반환되어야 함.
        """
        import whatwasthat.server.mcp as mcp_module
        from whatwasthat.models import Chunk, Turn
        from whatwasthat.search.engine import SearchEngine
        from whatwasthat.server.mcp import _reset_engine, search_memory
        from whatwasthat.storage.vector import VectorStore

        _reset_engine()
        vector = VectorStore(tmp_data_dir / "vector")
        vector.initialize()
        vector.upsert_chunks([
            Chunk(id="c1", session_id="s1",
                  turns=[Turn(role="user", content="React Hook 설계")],
                  raw_text="[user]: React useEffect Hook 패턴 논의",
                  project="frontend"),
        ])
        monkeypatch.setattr(mcp_module, "_engine", SearchEngine(vector=vector))

        result = search_memory(query="React Hook", project="projA", cwd=None)
        assert "frontend" in result or "React" in result
        _reset_engine()

    def test_search_does_not_mutate_access_count(
        self, tmp_data_dir, monkeypatch,
    ):
        """v1.0.11.2 회귀 방지: search는 access_count를 절대 건드리지 않는다.

        v1.0.11.1까지는 search 후 hit chunk들의 access_count가 +1 증가했다.
        멀티 프로세스 환경에서 ChromaDB 커넥션 라우팅 이슈로 SQLITE_READONLY를
        유발했기 때문에, v1.0.11.2부터는 search 경로에서 write를 완전히
        제거했다. access_count 증가는 v1.0.12의 recall_chunk에서만 발생.
        """
        import whatwasthat.server.mcp as mcp_module
        from whatwasthat.models import Chunk, Turn
        from whatwasthat.search.engine import SearchEngine
        from whatwasthat.server.mcp import _reset_engine, search_memory
        from whatwasthat.storage.vector import VectorStore

        _reset_engine()
        vector = VectorStore(tmp_data_dir / "vector")
        vector.initialize()
        vector.upsert_chunks([
            Chunk(id="c1", session_id="s1",
                  turns=[Turn(role="user", content="Kuzu 대신 Chroma 선택")],
                  raw_text="[user]: Kuzu 대신 Chroma 선택 이유 설명",
                  project="wwt"),
        ])

        # 사이드이펙트 감지: increment_access_counts가 호출되면 즉시 폭발
        def must_not_be_called(_ids):
            raise RuntimeError(
                "search must not mutate access_count (v1.0.11.2 regression)",
            )
        monkeypatch.setattr(vector, "increment_access_counts", must_not_be_called)
        monkeypatch.setattr(mcp_module, "_engine", SearchEngine(vector=vector))

        # search가 정상적으로 결과를 반환해야 한다
        result = search_memory(query="Chroma", project="wwt", cwd=None)
        assert "찾지 못했습니다" not in result
        assert ("Chroma" in result or "Kuzu" in result)

        # 메타데이터 직접 확인: access_count는 여전히 0
        meta = vector._get_collection().get(ids=["c1"], include=["metadatas"])
        assert meta["metadatas"][0]["access_count"] == 0
        _reset_engine()

    def test_search_result_format_includes_timestamp(self, tmp_data_dir, monkeypatch):
        """검색 결과 출력에 날짜/시간이 포함되어야 한다."""
        from datetime import datetime, timezone

        import whatwasthat.server.mcp as mcp_module
        from whatwasthat.models import Chunk, Turn
        from whatwasthat.search.engine import SearchEngine
        from whatwasthat.server.mcp import _reset_engine, search_memory
        from whatwasthat.storage.vector import VectorStore

        _reset_engine()

        vector = VectorStore(tmp_data_dir / "vector")
        vector.initialize()
        ts = datetime(2026, 4, 7, 10, 30, 0, tzinfo=timezone.utc)
        chunks = [
            Chunk(id="ch1", session_id="s1",
                  turns=[Turn(role="user", content="DB 선택 논의")],
                  raw_text="[user]: DB는 Kuzu로 선택했어\n[assistant]: Kuzu는 그래프 DB입니다.",
                  project="testproj", git_branch="main", timestamp=ts),
        ]
        vector.upsert_chunks(chunks)

        # engine 싱글톤을 직접 주입하여 동일한 VectorStore 사용
        monkeypatch.setattr(mcp_module, "_engine", SearchEngine(vector=vector))

        result = search_memory(query="Kuzu DB", project="testproj", cwd=None)
        assert "2026-04-07" in result
        _reset_engine()

    def test_recall_chunk_returns_full_raw_and_updates_access_count(
        self, tmp_data_dir, monkeypatch,
    ):
        import whatwasthat.server.mcp as mcp_module
        from whatwasthat import config
        from whatwasthat.models import Chunk, CodeSnippet, RawSpan
        from whatwasthat.search.engine import SearchEngine
        from whatwasthat.server.mcp import _reset_engine, recall_chunk
        from whatwasthat.storage.raw_store import RawSpanStore
        from whatwasthat.storage.vector import VectorStore

        monkeypatch.setattr(config, "WWT_DATA_DIR", tmp_data_dir)
        monkeypatch.setattr(config, "CHROMA_DB_PATH", tmp_data_dir / "vector")
        _reset_engine()

        vector = VectorStore(tmp_data_dir / "vector")
        vector.initialize()
        raw_store = RawSpanStore(tmp_data_dir / "raw" / "spans.db")
        raw_store.initialize()

        full_raw = "[user]: " + ("원문 전체 보존 " * 120)
        snippet = CodeSnippet(id="span1_s0", language="python", code="print('hello')")
        raw_store.upsert_spans([
            RawSpan(
                id="span1",
                session_id="s1",
                start_turn_index=0,
                end_turn_index=1,
                raw_text=full_raw,
                code_snippets=[snippet],
                snippet_ids=["span1_s0"],
            ),
        ])
        vector.upsert_chunks([
            Chunk(
                id="c1",
                span_id="span1",
                session_id="s1",
                start_turn_index=0,
                end_turn_index=1,
                turn_count=2,
                search_text="원문 전체 보존",
                raw_preview=full_raw[:1000],
                raw_length=len(full_raw),
                snippet_ids=["span1_s0"],
                code_count=1,
                code_languages=["python"],
                project="proj",
            ),
        ])
        monkeypatch.setattr(mcp_module, "_engine", SearchEngine(vector=vector))
        monkeypatch.setattr(mcp_module, "_raw_store", raw_store)

        result = recall_chunk("c1")

        assert full_raw in result
        assert "```python id=span1_s0" in result
        assert raw_store.get_span("span1").access_count == 1
        meta = vector._get_collection().get(ids=["c1"], include=["metadatas"])
        assert meta["metadatas"][0]["access_count"] == 1
        _reset_engine()
