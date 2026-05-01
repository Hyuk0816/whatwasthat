"""원격 ingest/search용 FastAPI app."""

from __future__ import annotations

import hashlib
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status

from whatwasthat.config import WwtConfig
from whatwasthat.models import SessionMeta
from whatwasthat.pipeline.chunker import chunk_turns
from whatwasthat.pipeline.parser import detect_parser
from whatwasthat.remote.config import RemoteGatewayConfig
from whatwasthat.remote.models import (
    RemoteIngestBatchRequest,
    RemoteRecallRequest,
    RemoteSearchRequest,
    RemoteTextResponse,
    RemoteUploadSummary,
)
from whatwasthat.server.mcp import (
    _write_lock as _shared_write_lock,
)
from whatwasthat.server.mcp import (
    recall_chunk as _local_recall_chunk,
)
from whatwasthat.server.mcp import (
    search_all as _local_search_all,
)
from whatwasthat.server.mcp import (
    search_decision as _local_search_decision,
)
from whatwasthat.server.mcp import (
    search_memory as _local_search_memory,
)
from whatwasthat.storage.checkpoints import RemoteIngestCheckpointStore
from whatwasthat.storage.raw_store import RawSpanStore
from whatwasthat.storage.vector import VectorStore

PIPELINE_VERSION = "remote-ingest-v1"


def _build_token_checker(api_token: str | None):
    def _require_bearer_token(
        authorization: str | None = Header(default=None),
    ) -> None:
        if not api_token:
            return
        expected = f"Bearer {api_token}"
        if authorization != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
            )

    return _require_bearer_token


def _session_hash(transcript_text: str) -> str:
    return hashlib.sha256(transcript_text.encode("utf-8")).hexdigest()


def _default_stores():
    config = WwtConfig()
    raw_store = RawSpanStore(config.raw_spans_path)
    raw_store.initialize()
    vector_store = VectorStore(config.chroma_path)
    vector_store.initialize()
    checkpoints = RemoteIngestCheckpointStore(config.data_dir / "remote" / "checkpoints.db")
    checkpoints.initialize()
    return checkpoints, raw_store, vector_store


@contextmanager
def _write_lock():
    with _shared_write_lock():
        yield


def _parse_turns_from_session(filename: str, transcript_text: str):
    suffix = Path(filename).suffix or ".jsonl"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=suffix,
        delete=False,
    ) as temp_file:
        temp_file.write(transcript_text)
        temp_path = Path(temp_file.name)

    try:
        parser = detect_parser(temp_path)
        if parser is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported transcript format: {filename}",
            )
        return parser.parse_turns(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _search_memory_text(request: RemoteSearchRequest) -> str:
    return _local_search_memory(
        query=request.query,
        project=request.project,
        cwd=None,
        source=request.source,
        git_branch=request.git_branch,
        date=request.date,
        env=request.env,
    )


def _search_decision_text(request: RemoteSearchRequest) -> str:
    return _local_search_decision(
        query=request.query,
        project=request.project,
        cwd=None,
        source=request.source,
        git_branch=request.git_branch,
        date=request.date,
        env=request.env,
    )


def _search_all_text(request: RemoteSearchRequest) -> str:
    return _local_search_all(
        query=request.query,
        date=request.date,
        env=request.env,
    )


def _recall_chunk_text(request: RemoteRecallRequest) -> str:
    return _local_recall_chunk(
        chunk_id=request.chunk_id,
        include_neighbors=request.include_neighbors,
    )


def create_app(
    *,
    api_token: str | None = None,
    checkpoints: RemoteIngestCheckpointStore | None = None,
    raw_store: RawSpanStore | None = None,
    vector_store: VectorStore | None = None,
) -> FastAPI:
    app = FastAPI()
    require_bearer_token = _build_token_checker(
        api_token if api_token is not None else RemoteGatewayConfig.from_env().api_token,
    )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/v1/ingest/sessions")
    def ingest_sessions(
        request: RemoteIngestBatchRequest,
        _auth: None = Depends(require_bearer_token),
    ) -> RemoteUploadSummary:
        resolved_checkpoints = checkpoints
        resolved_raw_store = raw_store
        resolved_vector_store = vector_store
        if (
            resolved_checkpoints is None
            or resolved_raw_store is None
            or resolved_vector_store is None
        ):
            default_checkpoints, default_raw_store, default_vector_store = _default_stores()
            resolved_checkpoints = resolved_checkpoints or default_checkpoints
            resolved_raw_store = resolved_raw_store or default_raw_store
            resolved_vector_store = resolved_vector_store or default_vector_store

        uploaded = 0
        skipped = 0
        failed = 0
        mutated = False

        with _write_lock():
            for session in request.sessions:
                transcript_hash = _session_hash(session.transcript_text)
                if resolved_checkpoints.should_skip(
                    env=session.env,
                    source=session.source,
                    original_session_id=session.original_session_id,
                    transcript_hash=transcript_hash,
                    pipeline_version=PIPELINE_VERSION,
                ):
                    skipped += 1
                    continue

                try:
                    turns = _parse_turns_from_session(session.filename, session.transcript_text)
                    canonical_session_id = (
                        f"{session.env}:{session.source}:{session.original_session_id}"
                    )
                    meta = SessionMeta(
                        session_id=canonical_session_id,
                        project=session.project,
                        project_path=session.project_path,
                        git_branch=session.git_branch,
                        started_at=session.started_at,
                        env=session.env,
                        source=session.source,
                        turn_count=len(turns),
                    )
                    spans, chunks = chunk_turns(
                        turns,
                        session_id=canonical_session_id,
                        meta=meta,
                    )
                    resolved_raw_store.upsert_spans(spans)
                    resolved_vector_store.upsert_session_chunks(
                        canonical_session_id,
                        chunks,
                        rebuild_bm25=False,
                    )
                    resolved_checkpoints.record(
                        env=session.env,
                        source=session.source,
                        original_session_id=session.original_session_id,
                        transcript_hash=transcript_hash,
                        pipeline_version=PIPELINE_VERSION,
                    )
                    uploaded += 1
                    mutated = True
                except HTTPException:
                    raise
                except Exception:
                    failed += 1

            if mutated:
                resolved_vector_store.rebuild_index()

        return RemoteUploadSummary(uploaded=uploaded, skipped=skipped, failed=failed)

    @app.post("/v1/search/memory")
    def search_memory(
        request: RemoteSearchRequest,
        _auth: None = Depends(require_bearer_token),
    ) -> RemoteTextResponse:
        return RemoteTextResponse(text=_search_memory_text(request))

    @app.post("/v1/search/decision")
    def search_decision(
        request: RemoteSearchRequest,
        _auth: None = Depends(require_bearer_token),
    ) -> RemoteTextResponse:
        return RemoteTextResponse(text=_search_decision_text(request))

    @app.post("/v1/search/all")
    def search_all(
        request: RemoteSearchRequest,
        _auth: None = Depends(require_bearer_token),
    ) -> RemoteTextResponse:
        return RemoteTextResponse(text=_search_all_text(request))

    @app.post("/v1/recall/chunk")
    def recall_chunk(
        request: RemoteRecallRequest,
        _auth: None = Depends(require_bearer_token),
    ) -> RemoteTextResponse:
        return RemoteTextResponse(text=_recall_chunk_text(request))

    return app


def build_app(
    *,
    api_token: str | None = None,
    checkpoints: RemoteIngestCheckpointStore | None = None,
    raw_store: RawSpanStore | None = None,
    vector_store: VectorStore | None = None,
) -> FastAPI:
    return create_app(
        api_token=api_token,
        checkpoints=checkpoints,
        raw_store=raw_store,
        vector_store=vector_store,
    )


def main() -> None:
    import uvicorn

    config = RemoteGatewayConfig.from_env()
    uvicorn.run(
        build_app(api_token=config.api_token),
        host="0.0.0.0",
        port=8000,
    )
