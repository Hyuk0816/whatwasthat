"""WWT 공통 데이터 모델."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """대화 한 턴."""

    role: str
    content: str
    timestamp: datetime | None = None
    source: str = "claude-code"
    code_snippets: list[dict[str, str]] = []


class Chunk(BaseModel):
    """주제 단위 대화 청크."""

    id: str
    session_id: str
    turns: list[Turn]
    raw_text: str
    timestamp: datetime | None = None
    project: str = ""
    project_path: str = ""
    git_branch: str = ""
    source: str = "claude-code"
    code_snippets: list[dict[str, str]] = []
    start_turn_index: int = 0  # 세션 내 시작 턴 인덱스 (OP-RAG 순서 보존)
    access_count: int = 0  # 검색 회수 (Spaced Repetition 감쇠율 조절용)


class SessionMeta(BaseModel):
    """세션 메타데이터."""

    session_id: str
    project: str
    project_path: str
    git_branch: str
    started_at: datetime
    turn_count: int = 0
    source: str = "claude-code"


class SearchResult(BaseModel):
    """검색 결과."""

    session_id: str
    chunks: list[Chunk]
    summary: str
    score: float = Field(ge=0.0, le=1.0)
    project: str = ""
    git_branch: str = ""
    source: str = "claude-code"
    started_at: datetime | None = None
