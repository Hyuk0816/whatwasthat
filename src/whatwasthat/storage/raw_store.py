"""SQLite-backed canonical raw span storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from whatwasthat.models import CodeSnippet, RawSpan


class RawSpanStore:
    """Point lookup store for full raw conversation spans."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_spans (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    start_turn_index INTEGER NOT NULL,
                    end_turn_index INTEGER NOT NULL,
                    raw_text TEXT NOT NULL,
                    code_snippets TEXT NOT NULL DEFAULT '[]',
                    snippet_ids TEXT NOT NULL DEFAULT '[]',
                    access_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """,
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_spans_session ON raw_spans(session_id)",
            )

    def upsert_spans(self, spans: list[RawSpan]) -> None:
        if not spans:
            return
        self.initialize()
        rows = [
            (
                span.id,
                span.session_id,
                span.start_turn_index,
                span.end_turn_index,
                span.raw_text,
                json.dumps(
                    [s.model_dump() for s in span.code_snippets],
                    ensure_ascii=False,
                ),
                json.dumps(span.snippet_ids, ensure_ascii=False),
            )
            for span in spans
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO raw_spans (
                    id, session_id, start_turn_index, end_turn_index,
                    raw_text, code_snippets, snippet_ids
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    session_id=excluded.session_id,
                    start_turn_index=excluded.start_turn_index,
                    end_turn_index=excluded.end_turn_index,
                    raw_text=excluded.raw_text,
                    code_snippets=excluded.code_snippets,
                    snippet_ids=excluded.snippet_ids
                """,
                rows,
            )

    def get_span(self, span_id: str) -> RawSpan | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, start_turn_index, end_turn_index, raw_text,
                       code_snippets, snippet_ids, access_count
                FROM raw_spans
                WHERE id = ?
                """,
                (span_id,),
            ).fetchone()
        return self._row_to_span(row) if row else None

    def get_spans_by_session(self, session_id: str) -> list[RawSpan]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, start_turn_index, end_turn_index, raw_text,
                       code_snippets, snippet_ids, access_count
                FROM raw_spans
                WHERE session_id = ?
                ORDER BY start_turn_index ASC, end_turn_index ASC
                """,
                (session_id,),
            ).fetchall()
        return [span for row in rows if (span := self._row_to_span(row)) is not None]

    def get_neighbor_spans(self, span: RawSpan, include_neighbors: int) -> list[RawSpan]:
        if include_neighbors <= 0:
            return [span]

        spans = self.get_spans_by_session(span.session_id)
        try:
            index = next(i for i, candidate in enumerate(spans) if candidate.id == span.id)
        except StopIteration:
            return [span]
        start = max(0, index - include_neighbors)
        end = min(len(spans), index + include_neighbors + 1)
        return spans[start:end]

    def increment_access_count(self, span_id: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "UPDATE raw_spans SET access_count = access_count + 1 WHERE id = ?",
                (span_id,),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_span(row: sqlite3.Row | None) -> RawSpan | None:
        if row is None:
            return None
        snippets = [
            CodeSnippet(**item)
            for item in json.loads(row["code_snippets"] or "[]")
        ]
        return RawSpan(
            id=row["id"],
            session_id=row["session_id"],
            start_turn_index=int(row["start_turn_index"]),
            end_turn_index=int(row["end_turn_index"]),
            raw_text=row["raw_text"],
            code_snippets=snippets,
            snippet_ids=list(json.loads(row["snippet_ids"] or "[]")),
            access_count=int(row["access_count"] or 0),
        )
