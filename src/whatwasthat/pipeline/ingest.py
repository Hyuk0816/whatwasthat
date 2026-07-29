"""Reusable single-transcript ingestion preparation and storage operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whatwasthat.models import Chunk, RawSpan
from whatwasthat.pipeline.chunker import chunk_turns
from whatwasthat.pipeline.parser import detect_parser

if TYPE_CHECKING:
    from whatwasthat.storage.raw_store import RawSpanStore
    from whatwasthat.storage.vector import VectorStore


class PermanentIngestError(ValueError):
    """A transcript cannot become ingestible without being enqueued again."""


@dataclass(frozen=True)
class PreparedTranscript:
    path: Path
    session_id: str
    spans: tuple[RawSpan, ...]
    chunks: tuple[Chunk, ...]


@dataclass(frozen=True)
class IngestResult:
    session_id: str
    spans: int
    chunks: int
    embedded: int


def prepare_transcript(path: Path) -> PreparedTranscript:
    """Parse and chunk a transcript without opening any WWT database."""
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise PermanentIngestError(f"transcript does not exist: {resolved}")
    if resolved.stat().st_size == 0:
        raise PermanentIngestError(f"transcript is empty: {resolved}")
    parser = detect_parser(resolved)
    if parser is None:
        raise PermanentIngestError(f"unsupported transcript format: {resolved}")
    turns = parser.parse_turns(resolved)
    if not turns:
        raise PermanentIngestError(f"no conversation turns parsed: {resolved}")
    session_id = resolved.stem
    spans, chunks = chunk_turns(
        turns,
        session_id=session_id,
        meta=parser.parse_meta(resolved),
    )
    if not chunks:
        raise PermanentIngestError(f"no searchable chunks produced: {resolved}")
    return PreparedTranscript(
        path=resolved,
        session_id=session_id,
        spans=tuple(spans),
        chunks=tuple(chunks),
    )


def store_prepared_transcript(
    prepared: PreparedTranscript,
    *,
    raw_store: RawSpanStore,
    vector_store: VectorStore,
    rebuild_bm25: bool,
) -> IngestResult:
    """Idempotently store one prepared transcript."""
    raw_store.upsert_spans(list(prepared.spans))
    embedded = vector_store.upsert_session_chunks(
        prepared.session_id,
        list(prepared.chunks),
        rebuild_bm25=rebuild_bm25,
    )
    return IngestResult(
        session_id=prepared.session_id,
        spans=len(prepared.spans),
        chunks=len(prepared.chunks),
        embedded=embedded,
    )
