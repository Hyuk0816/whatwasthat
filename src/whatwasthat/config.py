"""WWT 설정 - 경로, 임베딩 설정, 상수."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

WWT_HOME = Path.home() / ".wwt"
WWT_DATA_DIR = WWT_HOME / "data"
CHROMA_DB_PATH = WWT_DATA_DIR / "vector"
BM25_INDEX_DIR = WWT_DATA_DIR / "bm25"
BM25_INDEX_PATH = BM25_INDEX_DIR / "index.pkl"
BM25_VERSION_PATH = BM25_INDEX_DIR / "version.txt"

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"


class WwtConfig(BaseModel):
    """WWT 전역 설정."""

    home_dir: Path = WWT_HOME
    data_dir: Path = WWT_DATA_DIR
    chroma_path: Path = CHROMA_DB_PATH
    bm25_index_path: Path = BM25_INDEX_PATH
    bm25_version_path: Path = BM25_VERSION_PATH
    embedding_model: str = EMBEDDING_MODEL
