"""WWT 공통 데이터 모델."""

from datetime import datetime

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """대화 한 턴."""

    role: str
    content: str
    timestamp: datetime | None = None


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


class SessionMeta(BaseModel):
    """세션 메타데이터."""

    session_id: str
    project: str
    project_path: str
    git_branch: str
    started_at: datetime
    turn_count: int = 0


class SearchResult(BaseModel):
    """검색 결과."""

    session_id: str
    chunks: list[Chunk]
    summary: str
    score: float = Field(ge=0.0, le=1.0)
    project: str = ""
    git_branch: str = ""
