"""원격 메모리 게이트웨이 HTTP 클라이언트."""

from __future__ import annotations

import httpx

from whatwasthat.remote.config import RemoteGatewayConfig
from whatwasthat.remote.models import (
    DiscoveredSession,
    RemoteIngestBatchRequest,
    RemoteRecallRequest,
    RemoteSearchRequest,
    RemoteTextResponse,
    RemoteUploadSummary,
)


class RemoteGatewayClient:
    """원격 게이트웨이에 ingest/search/recall 요청을 보낸다."""

    def __init__(self, config: RemoteGatewayConfig):
        self.config = config

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        return headers

    def ingest_sessions(self, sessions: list[DiscoveredSession]) -> RemoteUploadSummary:
        payload = RemoteIngestBatchRequest(sessions=sessions)

        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(
                self.config.ingest_url,
                json=payload.model_dump(mode="json"),
                headers=self._headers(),
            )
            response.raise_for_status()

        data = response.json() if response.content else {}
        return RemoteUploadSummary.model_validate(data)

    def upload_sessions(self, sessions: list[DiscoveredSession]) -> RemoteUploadSummary:
        return self.ingest_sessions(sessions)

    def _post_text(self, url: str, payload: RemoteSearchRequest | RemoteRecallRequest) -> str:
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(
                url,
                json=payload.model_dump(mode="json"),
                headers=self._headers(),
            )
            response.raise_for_status()

        data = response.json() if response.content else {}
        return RemoteTextResponse.model_validate(data).text

    def search_memory(
        self,
        *,
        query: str,
        env: str | None = None,
        project: str | None = None,
        source: str | None = None,
        git_branch: str | None = None,
        date: str | None = None,
    ) -> str:
        return self._post_text(
            self.config.search_memory_url,
            RemoteSearchRequest(
                query=query,
                env=env,
                project=project,
                source=source,
                git_branch=git_branch,
                date=date,
            ),
        )

    def search_decision(
        self,
        *,
        query: str,
        env: str | None = None,
        project: str | None = None,
        source: str | None = None,
        git_branch: str | None = None,
        date: str | None = None,
    ) -> str:
        return self._post_text(
            self.config.search_decision_url,
            RemoteSearchRequest(
                query=query,
                env=env,
                project=project,
                source=source,
                git_branch=git_branch,
                date=date,
            ),
        )

    def search_all(self, *, query: str, env: str | None = None, date: str | None = None) -> str:
        return self._post_text(
            self.config.search_all_url,
            RemoteSearchRequest(query=query, env=env, date=date),
        )

    def recall_chunk(self, *, chunk_id: str, include_neighbors: int = 0) -> str:
        return self._post_text(
            self.config.recall_chunk_url,
            RemoteRecallRequest(
                chunk_id=chunk_id,
                include_neighbors=include_neighbors,
            ),
        )
