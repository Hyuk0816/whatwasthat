"""WWT 공통 데이터 모델."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CodeSnippet(BaseModel):
    """원문 span에서 추출한 코드 블록."""

    id: str = ""
    language: str = "unknown"
    code: str


class Turn(BaseModel):
    """대화 한 턴."""

    role: str
    raw_text: str
    search_text: str
    timestamp: datetime | None = None
    source: str = "claude-code"
    code_snippets: list[CodeSnippet] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_content(cls, data):
        """Accept pre-v1.0.12 `content` inputs while callers are migrated."""
        if isinstance(data, dict) and "content" in data:
            content = data["content"]
            data = dict(data)
            data.setdefault("raw_text", content)
            data.setdefault("search_text", content)
        return data

class RawSpan(BaseModel):
    """무손실 원문 저장 단위."""

    id: str
    session_id: str
    start_turn_index: int
    end_turn_index: int
    raw_text: str
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    snippet_ids: list[str] = Field(default_factory=list)
    access_count: int = 0


class Chunk(BaseModel):
    """검색 인덱싱용 청크.

    원문 canonical data는 RawSpan에 저장하고, Chunk는 검색용 텍스트와 preview,
    RawSpan 참조만 가진다. pre-v1.0.12 입력은 validator가 얇게 흡수한다.
    """

    id: str
    span_id: str = ""
    session_id: str
    granularity: str = "small-window"
    start_turn_index: int = 0
    end_turn_index: int = 0
    turn_count: int = 0
    search_text: str
    raw_preview: str
    raw_length: int = 0
    timestamp: datetime | None = None
    project: str = ""
    project_path: str = ""
    git_branch: str = ""
    source: str = "claude-code"
    snippet_ids: list[str] = Field(default_factory=list)
    code_count: int = 0
    code_languages: list[str] = Field(default_factory=list)
    access_count: int = 0  # 검색 회수 (Spaced Repetition 감쇠율 조절용)

    @model_validator(mode="before")
    @classmethod
    def _migrate_chunk(cls, data):
        """Accept old Chunk(turns=..., raw_text=...) constructors."""
        if not isinstance(data, dict):
            return data

        data = dict(data)
        raw_text = data.get("raw_text")
        if raw_text is not None:
            data.setdefault("search_text", raw_text)
            data.setdefault("raw_preview", raw_text[:1000])
            data.setdefault("raw_length", len(raw_text))

        turns = data.get("turns") or []
        if turns:
            data.setdefault("turn_count", len(turns))
            data.setdefault(
                "end_turn_index",
                int(data.get("start_turn_index", 0) or 0) + len(turns) - 1,
            )

        code_snippets = data.get("code_snippets") or []
        if code_snippets:
            data.setdefault("code_count", len(code_snippets))
            languages: set[str] = set()
            snippet_ids: list[str] = []
            for index, snippet in enumerate(code_snippets):
                if isinstance(snippet, CodeSnippet):
                    language = snippet.language
                    snippet_id = snippet.id
                else:
                    language = snippet.get("language", "unknown")
                    snippet_id = snippet.get("id", "")
                languages.add(language or "unknown")
                if snippet_id:
                    snippet_ids.append(snippet_id)
                else:
                    span_id = data.get("span_id") or data.get("id") or "legacy"
                    snippet_ids.append(f"{span_id}_s{index}")
            data.setdefault("code_languages", sorted(languages))
            data.setdefault("snippet_ids", snippet_ids)

        if not data.get("span_id"):
            start = int(data.get("start_turn_index", 0) or 0)
            end = int(data.get("end_turn_index", start) or start)
            session_id = data.get("session_id", "")
            data["span_id"] = f"{session_id}:s{start}e{end}"

        data.setdefault("search_text", data.get("raw_preview", ""))
        data.setdefault("raw_preview", data.get("search_text", "")[:1000])
        data.setdefault("raw_length", len(data.get("raw_preview", "")))
        data.setdefault("turn_count", 0)
        return data

    @property
    def has_more(self) -> bool:
        """Whether RawSpan has more text than the preview."""
        return self.raw_length > len(self.raw_preview)


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
