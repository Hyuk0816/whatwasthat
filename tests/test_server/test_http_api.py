"""원격 ingest/search HTTP API 검증."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from whatwasthat.models import Turn
from whatwasthat.server.http_api import build_app, create_app


class _FakeCheckpoints:
    def __init__(self, skip_ids: set[tuple[str, str, str]] | None = None):
        self.skip_ids = skip_ids or set()
        self.records: list[dict] = []

    def should_skip(
        self,
        *,
        env: str,
        source: str,
        original_session_id: str,
        transcript_hash: str,
        pipeline_version: str,
    ) -> bool:
        return (env, source, original_session_id) in self.skip_ids

    def record(self, **kwargs) -> None:
        self.records.append(kwargs)


class _FakeRawStore:
    def __init__(self):
        self.spans: list = []

    def upsert_spans(self, spans):
        self.spans.extend(spans)


class _FakeVector:
    def __init__(self):
        self.upserts: list[dict] = []
        self.rebuild_calls = 0

    def upsert_session_chunks(self, session_id, chunks, *, rebuild_bm25=True):
        self.upserts.append(
            {
                "session_id": session_id,
                "chunks": list(chunks),
                "rebuild_bm25": rebuild_bm25,
            }
        )
        return len(chunks)

    def rebuild_index(self):
        self.rebuild_calls += 1


class _FakeParser:
    def parse_turns(self, file_path):
        return [
            Turn(role="user", raw_text="질문 " * 60, search_text="질문 " * 60),
            Turn(role="assistant", raw_text="답변 " * 60, search_text="답변 " * 60),
        ]


def test_build_app_alias_preserves_create_app_behavior():
    client = TestClient(build_app(api_token="secret"))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_healthz_returns_ok():
    app = create_app(api_token="secret")
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_ingest_requires_bearer_token():
    app = create_app(api_token="secret")
    client = TestClient(app)

    response = client.post("/v1/ingest/sessions", json={"sessions": []})

    assert response.status_code == 401


def test_ingest_batches_and_skips_by_checkpoint(monkeypatch):
    fake_checkpoints = _FakeCheckpoints(skip_ids={("home", "codex-cli", "sess-2")})
    fake_raw_store = _FakeRawStore()
    fake_vector = _FakeVector()

    monkeypatch.setattr("whatwasthat.server.http_api.detect_parser", lambda _: _FakeParser())

    app = create_app(
        api_token="secret",
        checkpoints=fake_checkpoints,
        raw_store=fake_raw_store,
        vector_store=fake_vector,
    )
    client = TestClient(app)

    payload = {
        "sessions": [
            {
                "env": "home",
                "source": "codex-cli",
                "project": "whatwasthat",
                "project_path": "/repo/whatwasthat",
                "git_branch": "main",
                "original_session_id": "sess-1",
                "filename": "sess-1.jsonl",
                "started_at": datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
                "transcript_text": "line one\nline two\n",
            },
            {
                "env": "home",
                "source": "codex-cli",
                "project": "whatwasthat",
                "project_path": "/repo/whatwasthat",
                "git_branch": "main",
                "original_session_id": "sess-2",
                "filename": "sess-2.jsonl",
                "started_at": datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
                "transcript_text": "line three\nline four\n",
            },
        ]
    }

    response = client.post(
        "/v1/ingest/sessions",
        headers={"Authorization": "Bearer secret"},
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["uploaded"] == 1
    assert response.json()["skipped"] == 1
    assert response.json()["failed"] == 0
    assert len(fake_vector.upserts) == 1
    assert fake_vector.upserts[0]["session_id"] == "home:codex-cli:sess-1"
    assert fake_vector.upserts[0]["rebuild_bm25"] is False
    assert fake_vector.rebuild_calls == 1
    assert len(fake_checkpoints.records) == 1


def test_ingest_uses_write_lock(monkeypatch):
    fake_checkpoints = _FakeCheckpoints()
    fake_raw_store = _FakeRawStore()
    fake_vector = _FakeVector()
    lock_events: list[str] = []

    @contextmanager
    def _fake_lock():
        lock_events.append("entered")
        try:
            yield
        finally:
            lock_events.append("exited")

    monkeypatch.setattr("whatwasthat.server.http_api.detect_parser", lambda _: _FakeParser())
    monkeypatch.setattr("whatwasthat.server.http_api._write_lock", _fake_lock)

    app = create_app(
        api_token="secret",
        checkpoints=fake_checkpoints,
        raw_store=fake_raw_store,
        vector_store=fake_vector,
    )
    client = TestClient(app)

    payload = {
        "sessions": [
            {
                "env": "home",
                "source": "codex-cli",
                "project": "whatwasthat",
                "project_path": "/repo/whatwasthat",
                "git_branch": "main",
                "original_session_id": "sess-1",
                "filename": "sess-1.jsonl",
                "started_at": datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
                "transcript_text": "line one\nline two\n",
            }
        ]
    }

    response = client.post(
        "/v1/ingest/sessions",
        headers={"Authorization": "Bearer secret"},
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert lock_events == ["entered", "exited"]


def test_search_endpoints_require_bearer_token():
    app = create_app(api_token="secret")
    client = TestClient(app)

    endpoints = [
        ("/v1/search/memory", {"query": "Redis"}),
        ("/v1/search/decision", {"query": "왜 Redis"}),
        ("/v1/search/all", {"query": "Redis"}),
        ("/v1/recall/chunk", {"chunk_id": "abc123"}),
    ]

    for path, payload in endpoints:
        response = client.post(path, json=payload)
        assert response.status_code == 401


def test_search_endpoints_return_text_payload(monkeypatch):
    captured: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "whatwasthat.server.http_api._search_memory_text",
        lambda request: captured.append(("memory", request)) or "memory result",
    )
    monkeypatch.setattr(
        "whatwasthat.server.http_api._search_decision_text",
        lambda request: captured.append(("decision", request)) or "decision result",
    )
    monkeypatch.setattr(
        "whatwasthat.server.http_api._search_all_text",
        lambda request: captured.append(("all", request)) or "all result",
    )
    monkeypatch.setattr(
        "whatwasthat.server.http_api._recall_chunk_text",
        lambda request: captured.append(("recall", request)) or "recall result",
    )

    app = create_app(api_token="secret")
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}

    memory = client.post(
        "/v1/search/memory",
        headers=headers,
        json={"query": "Redis", "env": "home"},
    )
    decision = client.post(
        "/v1/search/decision",
        headers=headers,
        json={"query": "왜 Redis를 선택했지?", "env": "office"},
    )
    all_result = client.post(
        "/v1/search/all",
        headers=headers,
        json={"query": "Redis", "env": "home"},
    )
    recall = client.post(
        "/v1/recall/chunk",
        headers=headers,
        json={"chunk_id": "chunk-1", "include_neighbors": 1},
    )

    assert memory.status_code == 200
    assert memory.json() == {"text": "memory result"}
    assert decision.status_code == 200
    assert decision.json() == {"text": "decision result"}
    assert all_result.status_code == 200
    assert all_result.json() == {"text": "all result"}
    assert recall.status_code == 200
    assert recall.json() == {"text": "recall result"}
    assert captured[0][1].env == "home"
    assert captured[1][1].env == "office"
    assert captured[2][1].env == "home"
