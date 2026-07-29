"""WWT 테스트 공통 fixture."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_wwt_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """모든 테스트가 실제 ``~/.wwt`` 대신 임시 저장소만 사용하게 한다."""
    home_dir = tmp_path / "wwt_home"
    data_dir = home_dir / "data"
    data_dir.mkdir(parents=True)
    from whatwasthat import config

    monkeypatch.setenv("WWT_HOME", str(home_dir))
    monkeypatch.setattr(config, "WWT_HOME", home_dir)
    monkeypatch.setattr(config, "WWT_DATA_DIR", data_dir)
    monkeypatch.setattr(config, "CHROMA_DB_PATH", data_dir / "vector")
    monkeypatch.setattr(config, "RAW_SPANS_DB_PATH", data_dir / "raw" / "spans.db")
    monkeypatch.setattr(config, "BM25_INDEX_DIR", data_dir / "bm25")
    monkeypatch.setattr(config, "BM25_INDEX_PATH", data_dir / "bm25" / "index.pkl")
    monkeypatch.setattr(config, "BM25_VERSION_PATH", data_dir / "bm25" / "version.txt")
    monkeypatch.setattr(config, "INGEST_QUEUE_PATH", data_dir / "queue" / "jobs.db")
    monkeypatch.setattr(config, "WORKER_LOCK_PATH", data_dir / "worker.lock")
    return data_dir


@pytest.fixture
def tmp_data_dir(isolated_wwt_data_dir: Path) -> Path:
    """테스트용 임시 데이터 디렉토리."""
    return isolated_wwt_data_dir


@pytest.fixture
def sample_turns() -> list[dict]:
    """샘플 대화 턴 데이터."""
    return [
        {"role": "user", "content": "FastAPI 대신 Flask 쓰자"},
        {"role": "assistant", "content": "FastAPI가 async 지원이 좋으니 유지하는 게 어떨까요?"},
        {"role": "user", "content": "그래 FastAPI로 하자"},
    ]
