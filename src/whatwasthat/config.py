"""WWT 설정 - 경로, 임베딩 설정, 상수."""

from pathlib import Path

from pydantic import BaseModel

WWT_HOME = Path.home() / ".wwt"
WWT_DATA_DIR = WWT_HOME / "data"
CHROMA_DB_PATH = WWT_DATA_DIR / "vector"

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


class WwtConfig(BaseModel):
    """WWT 전역 설정."""

    home_dir: Path = WWT_HOME
    data_dir: Path = WWT_DATA_DIR
    chroma_path: Path = CHROMA_DB_PATH
    embedding_model: str = EMBEDDING_MODEL
