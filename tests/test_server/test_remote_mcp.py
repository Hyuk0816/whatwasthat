"""원격 MCP 도구 검증."""

from __future__ import annotations

from whatwasthat.server import mcp as mcp_module


class _FakeRemoteClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def search_memory(self, **kwargs):
        self.calls.append(("search_memory", kwargs))
        return "remote memory result"

    def search_decision(self, **kwargs):
        self.calls.append(("search_decision", kwargs))
        return "remote decision result"

    def search_all(self, **kwargs):
        self.calls.append(("search_all", kwargs))
        return "remote all result"

    def recall_chunk(self, **kwargs):
        self.calls.append(("recall_chunk", kwargs))
        return "remote recall result"


def test_server_registers_remote_tools():
    tools = list(mcp_module.mcp._tool_manager._tools.keys())

    assert "search_remote_memory" in tools
    assert "search_remote_decision" in tools
    assert "search_remote_all" in tools
    assert "recall_remote_chunk" in tools


def test_search_remote_memory_infers_project_from_cwd(monkeypatch):
    client = _FakeRemoteClient()
    monkeypatch.setattr(mcp_module, "_get_remote_client", lambda: client)

    result = mcp_module.search_remote_memory(
        query="recent technical decisions",
        env="home",
        project=None,
        cwd="/Users/hyuk/PycharmProjects/whatwasthat",
        source=None,
        git_branch=None,
        date="2026-05-01",
    )

    assert result == "remote memory result"
    assert client.calls == [
        (
            "search_memory",
            {
                "query": "recent technical decisions",
                "env": "home",
                "project": "whatwasthat",
                "source": None,
                "git_branch": None,
                "date": "2026-05-01",
            },
        )
    ]


def test_search_remote_decision_skips_cwd_project_inference_when_source_present(monkeypatch):
    client = _FakeRemoteClient()
    monkeypatch.setattr(mcp_module, "_get_remote_client", lambda: client)

    result = mcp_module.search_remote_decision(
        query="왜 Redis 대신 SQLite였지?",
        env="office",
        project=None,
        cwd="/Users/hyuk/PycharmProjects/whatwasthat",
        source="codex-cli",
        git_branch=None,
        date=None,
    )

    assert result == "remote decision result"
    assert client.calls == [
        (
            "search_decision",
            {
                "query": "왜 Redis 대신 SQLite였지?",
                "env": "office",
                "project": None,
                "source": "codex-cli",
                "git_branch": None,
                "date": None,
            },
        )
    ]


def test_search_remote_all_and_recall_chunk_delegate_to_remote_client(monkeypatch):
    client = _FakeRemoteClient()
    monkeypatch.setattr(mcp_module, "_get_remote_client", lambda: client)

    all_result = mcp_module.search_remote_all(
        query="mTLS cert chain",
        env="home",
        date="2026-05-01",
    )
    recall_result = mcp_module.recall_remote_chunk(
        chunk_id="chunk-1234",
        include_neighbors=2,
    )

    assert all_result == "remote all result"
    assert recall_result == "remote recall result"
    assert client.calls == [
        ("search_all", {"query": "mTLS cert chain", "env": "home", "date": "2026-05-01"}),
        ("recall_chunk", {"chunk_id": "chunk-1234", "include_neighbors": 2}),
    ]
