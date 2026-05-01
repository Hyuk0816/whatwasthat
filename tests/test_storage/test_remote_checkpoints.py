"""원격 ingest 체크포인트 동작 검증."""

from __future__ import annotations

from whatwasthat.storage.checkpoints import RemoteIngestCheckpointStore


def test_should_skip_when_hash_and_pipeline_match(tmp_data_dir):
    store = RemoteIngestCheckpointStore(tmp_data_dir / "remote" / "checkpoints.db")
    store.initialize()
    store.record(
        env="home",
        source="codex-cli",
        original_session_id="sess-1",
        transcript_hash="hash-a",
        pipeline_version="v1",
    )

    assert store.should_skip(
        env="home",
        source="codex-cli",
        original_session_id="sess-1",
        transcript_hash="hash-a",
        pipeline_version="v1",
    )


def test_should_reindex_when_hash_changes(tmp_data_dir):
    store = RemoteIngestCheckpointStore(tmp_data_dir / "remote" / "checkpoints.db")
    store.initialize()
    store.record(
        env="home",
        source="codex-cli",
        original_session_id="sess-1",
        transcript_hash="hash-a",
        pipeline_version="v1",
    )

    assert not store.should_skip(
        env="home",
        source="codex-cli",
        original_session_id="sess-1",
        transcript_hash="hash-b",
        pipeline_version="v1",
    )


def test_should_reindex_when_pipeline_version_changes(tmp_data_dir):
    store = RemoteIngestCheckpointStore(tmp_data_dir / "remote" / "checkpoints.db")
    store.initialize()
    store.record(
        env="home",
        source="codex-cli",
        original_session_id="sess-1",
        transcript_hash="hash-a",
        pipeline_version="v1",
    )

    assert not store.should_skip(
        env="home",
        source="codex-cli",
        original_session_id="sess-1",
        transcript_hash="hash-a",
        pipeline_version="v2",
    )
