"""원격 업로드/검색 요청·응답 모델."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from whatwasthat.models import SessionMeta


class RemoteIngestSession(BaseModel):
    """원격 ingest 대상 세션 payload."""

    env: str
    source: str
    project: str
    project_path: str
    git_branch: str
    original_session_id: str
    filename: str
    started_at: datetime
    transcript_text: str


class RemoteIngestBatchRequest(BaseModel):
    """배치 업로드 요청."""

    sessions: list[RemoteIngestSession] = Field(default_factory=list)


class RemoteUploadSummary(BaseModel):
    """여러 세션 업로드 결과 요약."""

    uploaded: int = 0
    skipped: int = 0
    failed: int = 0


class RemoteSearchRequest(BaseModel):
    """원격 search 계열 요청."""

    query: str
    env: str | None = None
    project: str | None = None
    source: str | None = None
    git_branch: str | None = None
    date: str | None = None


class RemoteRecallRequest(BaseModel):
    """원격 recall 요청."""

    chunk_id: str
    include_neighbors: int = 0


class RemoteTextResponse(BaseModel):
    """원격 search/recall 응답."""

    text: str


class DiscoveredSession(RemoteIngestSession):
    """로컬에서 발견한 업로드 대상 세션."""

    path: Path
    meta: SessionMeta | None = None


# Backward-compatible aliases for pre-batch imports.
RemoteSessionUploadRequest = RemoteIngestSession


class RemoteSessionUploadResponse(BaseModel):
    """단건 응답 호환용 모델."""

    ok: bool = True
    session_id: str = ""
    message: str = ""
