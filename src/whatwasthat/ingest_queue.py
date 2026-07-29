"""Durable SQLite queue for deferred transcript ingestion."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (5.0, 30.0)


@dataclass(frozen=True)
class IngestJob:
    transcript_path: Path
    source: str
    revision: int
    enqueued_at: float
    attempts: int
    next_attempt_at: float
    last_error: str | None
    state: str


@dataclass(frozen=True)
class QueueSummary:
    pending: int
    failed: int
    oldest_pending_at: float | None
    recent_errors: tuple[IngestJob, ...]


class IngestQueue:
    """Coalescing queue whose rows survive worker and host process restarts."""

    def __init__(self, db_path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.db_path = db_path
        self._clock = clock

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_jobs (
                    transcript_path TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    enqueued_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL,
                    last_error TEXT,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK (state IN ('pending', 'failed'))
                )
                """,
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingest_jobs_ready
                ON ingest_jobs(state, next_attempt_at, enqueued_at)
                """,
            )

    def enqueue(self, transcript_path: Path, *, source: str) -> IngestJob:
        self.initialize()
        path = str(transcript_path.expanduser().resolve(strict=False))
        now = self._clock()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_jobs (
                    transcript_path, source, revision, enqueued_at,
                    attempts, next_attempt_at, last_error, state
                ) VALUES (?, ?, 1, ?, 0, ?, NULL, 'pending')
                ON CONFLICT(transcript_path) DO UPDATE SET
                    source=excluded.source,
                    revision=ingest_jobs.revision + 1,
                    enqueued_at=excluded.enqueued_at,
                    attempts=0,
                    next_attempt_at=excluded.next_attempt_at,
                    last_error=NULL,
                    state='pending'
                """,
                (path, source, now, now),
            )
            row = conn.execute(
                "SELECT * FROM ingest_jobs WHERE transcript_path = ?",
                (path,),
            ).fetchone()
        return self._row_to_job(row)

    def ready(self, *, debounce_seconds: float, limit: int) -> list[IngestJob]:
        self.initialize()
        now = self._clock()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ingest_jobs
                WHERE state = 'pending'
                  AND next_attempt_at <= ?
                  AND enqueued_at <= ?
                ORDER BY enqueued_at ASC, transcript_path ASC
                LIMIT ?
                """,
                (now, now - max(0.0, debounce_seconds), limit),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def acknowledge(self, job: IngestJob) -> bool:
        self.initialize()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM ingest_jobs
                WHERE transcript_path = ? AND revision = ? AND state = 'pending'
                """,
                (str(job.transcript_path), job.revision),
            )
        return cursor.rowcount == 1

    def mark_transient_failure(self, job: IngestJob, error: str) -> str:
        """Schedule a retry, or mark the same revision failed after three attempts."""
        self.initialize()
        now = self._clock()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT revision, attempts FROM ingest_jobs WHERE transcript_path = ?",
                (str(job.transcript_path),),
            ).fetchone()
            if row is None or int(row["revision"]) != job.revision:
                return "superseded"
            attempts = int(row["attempts"]) + 1
            if attempts >= MAX_ATTEMPTS:
                state = "failed"
                next_attempt_at = now
            else:
                state = "pending"
                next_attempt_at = now + RETRY_DELAYS_SECONDS[attempts - 1]
            conn.execute(
                """
                UPDATE ingest_jobs
                SET attempts = ?, next_attempt_at = ?, last_error = ?, state = ?
                WHERE transcript_path = ? AND revision = ?
                """,
                (
                    attempts,
                    next_attempt_at,
                    error,
                    state,
                    str(job.transcript_path),
                    job.revision,
                ),
            )
        return state

    def mark_permanent_failure(self, job: IngestJob, error: str) -> bool:
        self.initialize()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE ingest_jobs
                SET attempts = attempts + 1, last_error = ?, state = 'failed'
                WHERE transcript_path = ? AND revision = ?
                """,
                (error, str(job.transcript_path), job.revision),
            )
        return cursor.rowcount == 1

    def list_jobs(self, *, state: str | None = None) -> list[IngestJob]:
        self.initialize()
        query = "SELECT * FROM ingest_jobs"
        params: tuple[str, ...] = ()
        if state is not None:
            query += " WHERE state = ?"
            params = (state,)
        query += " ORDER BY enqueued_at ASC, transcript_path ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def has_pending(self) -> bool:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM ingest_jobs WHERE state = 'pending' LIMIT 1",
            ).fetchone()
        return row is not None

    def summary(self, *, error_limit: int = 5) -> QueueSummary:
        self.initialize()
        with self._connect() as conn:
            counts = {
                row["state"]: int(row["count"])
                for row in conn.execute(
                    "SELECT state, COUNT(*) AS count FROM ingest_jobs GROUP BY state",
                ).fetchall()
            }
            oldest = conn.execute(
                "SELECT MIN(enqueued_at) AS value FROM ingest_jobs WHERE state = 'pending'",
            ).fetchone()["value"]
            errors = conn.execute(
                """
                SELECT * FROM ingest_jobs
                WHERE state = 'failed'
                ORDER BY enqueued_at DESC
                LIMIT ?
                """,
                (error_limit,),
            ).fetchall()
        return QueueSummary(
            pending=counts.get("pending", 0),
            failed=counts.get("failed", 0),
            oldest_pending_at=float(oldest) if oldest is not None else None,
            recent_errors=tuple(self._row_to_job(row) for row in errors),
        )

    @contextmanager
    def immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        """Block enqueue writers while a worker performs its final empty check."""
        self.initialize()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def pending_in_transaction(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM ingest_jobs WHERE state = 'pending' LIMIT 1",
        ).fetchone() is not None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _row_to_job(row: sqlite3.Row | None) -> IngestJob:
        if row is None:
            raise RuntimeError("ingest queue row unexpectedly missing")
        return IngestJob(
            transcript_path=Path(row["transcript_path"]),
            source=str(row["source"]),
            revision=int(row["revision"]),
            enqueued_at=float(row["enqueued_at"]),
            attempts=int(row["attempts"]),
            next_attempt_at=float(row["next_attempt_at"]),
            last_error=row["last_error"],
            state=str(row["state"]),
        )
