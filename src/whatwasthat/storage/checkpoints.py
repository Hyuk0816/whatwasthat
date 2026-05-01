"""원격 ingest 체크포인트 저장소."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class RemoteIngestCheckpointStore:
    """원격 ingest 중복/재색인 판단용 체크포인트."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS remote_ingest_checkpoints (
                    env TEXT NOT NULL,
                    source TEXT NOT NULL,
                    original_session_id TEXT NOT NULL,
                    transcript_hash TEXT NOT NULL,
                    pipeline_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (env, source, original_session_id)
                )
                """,
            )

    def should_skip(
        self,
        *,
        env: str,
        source: str,
        original_session_id: str,
        transcript_hash: str,
        pipeline_version: str,
    ) -> bool:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT transcript_hash, pipeline_version
                FROM remote_ingest_checkpoints
                WHERE env = ? AND source = ? AND original_session_id = ?
                """,
                (env, source, original_session_id),
            ).fetchone()
        if row is None:
            return False
        return (
            row["transcript_hash"] == transcript_hash
            and row["pipeline_version"] == pipeline_version
        )

    def record(
        self,
        *,
        env: str,
        source: str,
        original_session_id: str,
        transcript_hash: str,
        pipeline_version: str,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO remote_ingest_checkpoints (
                    env, source, original_session_id, transcript_hash, pipeline_version
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(env, source, original_session_id) DO UPDATE SET
                    transcript_hash=excluded.transcript_hash,
                    pipeline_version=excluded.pipeline_version,
                    updated_at=datetime('now')
                """,
                (env, source, original_session_id, transcript_hash, pipeline_version),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn
