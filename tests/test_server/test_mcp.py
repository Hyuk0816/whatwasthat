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
