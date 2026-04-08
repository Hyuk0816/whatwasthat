"""MCP 서버 테스트."""

import pytest

from whatwasthat.server.mcp import mcp


class TestMcpServer:
    def test_server_has_tools(self):
        tools = list(mcp._tool_manager._tools.keys())
        assert "search_memory" in tools
        assert "search_all" in tools
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
