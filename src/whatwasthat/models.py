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


class Triple(BaseModel):
    """Knowledge Graph 트리플."""

    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str
    temporal: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Entity(BaseModel):
    """그래프 엔티티 노드."""

    id: str
    name: str
    type: str
    aliases: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Session(BaseModel):
    """대화 세션."""

    id: str
    source: str
    created_at: datetime
    summary: str = ""


class SearchResult(BaseModel):
    """검색 결과."""

    session_id: str
    triples: list[Triple]
    summary: str
    score: float = Field(ge=0.0, le=1.0)
