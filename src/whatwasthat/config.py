"""WWT 설정 - 경로, 임베딩 설정, 상수."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


def _resolve_wwt_home() -> Path:
    """환경변수 override를 반영한 WWT 홈 디렉토리."""
    return Path(os.environ.get("WWT_HOME", "~/.wwt")).expanduser()


def _resolve_data_dir() -> Path:
    return _resolve_wwt_home() / "data"


def _resolve_chroma_path() -> Path:
    return _resolve_data_dir() / "vector"


def _resolve_raw_spans_path() -> Path:
    return _resolve_data_dir() / "raw" / "spans.db"


def _resolve_bm25_index_path() -> Path:
    return _resolve_data_dir() / "bm25" / "index.pkl"


def _resolve_bm25_version_path() -> Path:
    return _resolve_data_dir() / "bm25" / "version.txt"

WWT_HOME = _resolve_wwt_home()
WWT_DATA_DIR = _resolve_data_dir()
CHROMA_DB_PATH = _resolve_chroma_path()
RAW_SPANS_DB_PATH = _resolve_raw_spans_path()
BM25_INDEX_DIR = WWT_DATA_DIR / "bm25"
BM25_INDEX_PATH = _resolve_bm25_index_path()
BM25_VERSION_PATH = _resolve_bm25_version_path()

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"


class WwtConfig(BaseModel):
    """WWT 전역 설정."""

    home_dir: Path = Field(default_factory=_resolve_wwt_home)
    data_dir: Path = Field(default_factory=_resolve_data_dir)
    chroma_path: Path = Field(default_factory=_resolve_chroma_path)
    raw_spans_path: Path = Field(default_factory=_resolve_raw_spans_path)
    bm25_index_path: Path = Field(default_factory=_resolve_bm25_index_path)
    bm25_version_path: Path = Field(default_factory=_resolve_bm25_version_path)
    embedding_model: str = EMBEDDING_MODEL
