"""WWT 테스트 공통 fixture."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """테스트용 임시 데이터 디렉토리."""
    data_dir = tmp_path / "wwt_test"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def sample_turns() -> list[dict]:
    """샘플 대화 턴 데이터."""
    return [
        {"role": "user", "content": "FastAPI 대신 Flask 쓰자"},
        {"role": "assistant", "content": "FastAPI가 async 지원이 좋으니 유지하는 게 어떨까요?"},
        {"role": "user", "content": "그래 FastAPI로 하자"},
    ]
