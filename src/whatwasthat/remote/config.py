"""원격 메모리 게이트웨이 설정."""

from __future__ import annotations

import os

from pydantic import BaseModel


class RemoteGatewayConfig(BaseModel):
    """원격 ingest/search 엔드포인트 설정."""

    base_url: str = "http://127.0.0.1:8000"
    api_token: str | None = None
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> RemoteGatewayConfig:
        timeout_raw = os.environ.get("WWT_REMOTE_TIMEOUT_SECONDS")
        timeout_seconds = float(timeout_raw) if timeout_raw else 30.0
        return cls(
            base_url=os.environ.get("WWT_REMOTE_BASE_URL", "http://127.0.0.1:8000"),
            api_token=os.environ.get("WWT_REMOTE_API_TOKEN"),
            timeout_seconds=timeout_seconds,
        )

    @property
    def ingest_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/ingest/sessions"

    @property
    def search_memory_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/search/memory"

    @property
    def search_decision_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/search/decision"

    @property
    def search_all_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/search/all"

    @property
    def recall_chunk_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/recall/chunk"
