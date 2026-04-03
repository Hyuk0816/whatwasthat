"""WWT 설정 - 경로, Ollama 설정, 상수."""

from pathlib import Path

from pydantic import BaseModel


WWT_HOME = Path.home() / ".wwt"
WWT_DATA_DIR = WWT_HOME / "data"
KUZU_DB_PATH = WWT_DATA_DIR / "graph"
CHROMA_DB_PATH = WWT_DATA_DIR / "vector"

OLLAMA_MODEL = "qwen3:4b"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


class WwtConfig(BaseModel):
    """WWT 전역 설정."""

    home_dir: Path = WWT_HOME
    data_dir: Path = WWT_DATA_DIR
    kuzu_path: Path = KUZU_DB_PATH
    chroma_path: Path = CHROMA_DB_PATH
    ollama_model: str = OLLAMA_MODEL
    embedding_model: str = EMBEDDING_MODEL
