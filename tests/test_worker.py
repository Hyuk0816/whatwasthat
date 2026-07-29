from __future__ import annotations

import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

from whatwasthat.config import WwtConfig
from whatwasthat.ingest_queue import IngestQueue
from whatwasthat.pipeline.ingest import PermanentIngestError, prepare_transcript
from whatwasthat.storage.locking import InterProcessLock
from whatwasthat.worker import WorkerResources, process_jobs, run_worker


def _write_transcript(path: Path, topic: str) -> None:
    records = [
        {
            "type": "user",
            "message": {"role": "user", "content": f"{topic} 설계 결정 " * 30},
        },
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": f"{topic} 구현 설명 " * 30},
        },
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


class FakeRawStore:
    def __init__(self) -> None:
        self.sessions: list[str] = []

    def upsert_spans(self, spans) -> None:
        self.sessions.extend(span.session_id for span in spans)


class FakeVectorStore:
    def __init__(self, *, fail_session: str | None = None) -> None:
        self.sessions: list[str] = []
        self.rebuilds = 0
        self.fail_session = fail_session

    def upsert_session_chunks(self, session_id, chunks, *, rebuild_bm25=True):
        assert rebuild_bm25 is False
        if session_id == self.fail_session:
            raise RuntimeError("temporary vector failure")
        self.sessions.append(session_id)
        return len(chunks)

    def rebuild_index(self) -> None:
        self.rebuilds += 1


class CapturingVectorStore(FakeVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self.search_texts: list[str] = []

    def upsert_session_chunks(self, session_id, chunks, *, rebuild_bm25=True):
        self.search_texts.extend(chunk.search_text for chunk in chunks)
        return super().upsert_session_chunks(
            session_id,
            chunks,
            rebuild_bm25=rebuild_bm25,
        )


def _config(tmp_data_dir: Path) -> WwtConfig:
    return WwtConfig(
        home_dir=tmp_data_dir.parent,
        data_dir=tmp_data_dir,
        chroma_path=tmp_data_dir / "vector",
        raw_spans_path=tmp_data_dir / "raw" / "spans.db",
        bm25_index_path=tmp_data_dir / "bm25" / "index.pkl",
        bm25_version_path=tmp_data_dir / "bm25" / "version.txt",
        ingest_queue_path=tmp_data_dir / "queue" / "jobs.db",
        worker_lock_path=tmp_data_dir / "worker.lock",
    )


def test_process_jobs_ingests_multiple_platforms_and_rebuilds_once(tmp_data_dir: Path):
    first_path = tmp_data_dir / "first.jsonl"
    second_path = tmp_data_dir / "second.jsonl"
    _write_transcript(first_path, "Redis")
    _write_transcript(second_path, "PostgreSQL")
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db")
    first = queue.enqueue(first_path, source="codex-cli")
    second = queue.enqueue(second_path, source="gemini-cli")
    raw = FakeRawStore()
    vector = FakeVectorStore()

    result = process_jobs(
        queue,
        [first, second],
        config=_config(tmp_data_dir),
        resources=WorkerResources(raw_store=raw, vector_store=vector),
        lock_factory=lambda _: nullcontext(),
    )

    assert result.succeeded == 2
    assert result.rebuilt_bm25 is True
    assert vector.rebuilds == 1
    assert vector.sessions == ["first", "second"]
    assert queue.list_jobs() == []


def test_repeated_enqueue_processes_only_latest_file_contents(tmp_data_dir: Path):
    transcript = tmp_data_dir / "session.jsonl"
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db")

    for revision in range(20):
        _write_transcript(transcript, f"설계버전{revision}")
        latest_job = queue.enqueue(transcript, source="codex-cli")

    vector = CapturingVectorStore()
    result = process_jobs(
        queue,
        queue.ready(debounce_seconds=0, limit=16),
        config=_config(tmp_data_dir),
        resources=WorkerResources(raw_store=FakeRawStore(), vector_store=vector),
        lock_factory=lambda _: nullcontext(),
    )

    assert latest_job.revision == 20
    assert result.succeeded == 1
    assert any("설계버전19" in text for text in vector.search_texts)
    assert all("설계버전18" not in text for text in vector.search_texts)
    assert queue.list_jobs() == []


def test_one_transient_failure_does_not_block_other_job(tmp_data_dir: Path):
    failing_path = tmp_data_dir / "failing.jsonl"
    good_path = tmp_data_dir / "good.jsonl"
    _write_transcript(failing_path, "Redis")
    _write_transcript(good_path, "PostgreSQL")
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db")
    failing = queue.enqueue(failing_path, source="codex-cli")
    good = queue.enqueue(good_path, source="claude-code")
    vector = FakeVectorStore(fail_session="failing")

    result = process_jobs(
        queue,
        [failing, good],
        config=_config(tmp_data_dir),
        resources=WorkerResources(raw_store=FakeRawStore(), vector_store=vector),
        lock_factory=lambda _: nullcontext(),
    )

    assert result.succeeded == 1
    assert result.transient_failures == 1
    assert vector.sessions == ["good"]
    remaining = queue.list_jobs()
    assert len(remaining) == 1
    assert remaining[0].transcript_path == failing_path
    assert remaining[0].attempts == 1


def test_missing_transcript_is_permanent_and_does_not_touch_stores(tmp_data_dir: Path):
    missing = tmp_data_dir / "missing.jsonl"
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db")
    job = queue.enqueue(missing, source="codex-cli")
    vector = FakeVectorStore()

    result = process_jobs(
        queue,
        [job],
        config=_config(tmp_data_dir),
        resources=WorkerResources(raw_store=FakeRawStore(), vector_store=vector),
        lock_factory=lambda _: nullcontext(),
    )

    assert result.permanent_failures == 1
    assert vector.sessions == []
    assert vector.rebuilds == 0
    assert queue.list_jobs()[0].state == "failed"


def test_missing_transcript_does_not_initialize_heavy_resources(tmp_data_dir: Path):
    config = _config(tmp_data_dir)
    queue = IngestQueue(config.ingest_queue_path)
    queue.enqueue(tmp_data_dir / "missing.jsonl", source="codex-cli")
    factory_calls = 0

    def resource_factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return WorkerResources(raw_store=FakeRawStore(), vector_store=FakeVectorStore())

    result = run_worker(
        config=config,
        queue=queue,
        once=True,
        resource_factory=resource_factory,
        apply_priority=False,
    )

    assert result.cycles == 1
    assert factory_calls == 0
    assert queue.list_jobs()[0].state == "failed"


def test_run_worker_initializes_resources_once_for_multiple_cycles(tmp_data_dir: Path):
    first_path = tmp_data_dir / "first.jsonl"
    second_path = tmp_data_dir / "second.jsonl"
    _write_transcript(first_path, "Redis")
    _write_transcript(second_path, "PostgreSQL")
    config = _config(tmp_data_dir)
    queue = IngestQueue(config.ingest_queue_path)
    queue.enqueue(first_path, source="codex-cli")
    queue.enqueue(second_path, source="gemini-cli")
    vector = FakeVectorStore()
    factory_calls = 0

    def resource_factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return WorkerResources(raw_store=FakeRawStore(), vector_store=vector)

    result = run_worker(
        config=config,
        queue=queue,
        once=True,
        max_jobs=1,
        resource_factory=resource_factory,
        apply_priority=False,
    )

    assert result.cycles == 2
    assert factory_calls == 1
    assert vector.rebuilds == 2
    assert queue.list_jobs() == []


def test_prepare_transcript_rejects_empty_file_without_database_work(tmp_data_dir: Path):
    empty = tmp_data_dir / "empty.jsonl"
    empty.touch()

    try:
        prepare_transcript(empty)
    except PermanentIngestError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty transcript must be rejected")


def test_second_worker_exits_before_initializing_resources(tmp_data_dir: Path):
    config = _config(tmp_data_dir)
    held_lock = InterProcessLock(config.worker_lock_path)
    assert held_lock.acquire(blocking=False)
    factory_calls = 0

    def resource_factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return WorkerResources(raw_store=FakeRawStore(), vector_store=FakeVectorStore())

    try:
        result = run_worker(
            config=config,
            once=True,
            resource_factory=resource_factory,
            apply_priority=False,
        )
    finally:
        held_lock.release()

    assert result.already_running is True
    assert result.cycles == 0
    assert factory_calls == 0


def test_idle_worker_exits_without_initializing_heavy_resources(tmp_data_dir: Path):
    config = _config(tmp_data_dir)
    queue = IngestQueue(config.ingest_queue_path)
    monotonic_value = 0.0
    factory_calls = 0

    def monotonic():
        return monotonic_value

    def sleep(seconds):
        nonlocal monotonic_value
        monotonic_value += seconds

    def resource_factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return WorkerResources(raw_store=FakeRawStore(), vector_store=FakeVectorStore())

    result = run_worker(
        config=config,
        queue=queue,
        idle_timeout_seconds=3,
        poll_seconds=1,
        monotonic=monotonic,
        sleep=sleep,
        resource_factory=resource_factory,
        apply_priority=False,
    )

    assert result.cycles == 0
    assert factory_calls == 0
    probe = InterProcessLock(config.worker_lock_path)
    assert probe.acquire(blocking=False)
    probe.release()


def test_worker_control_import_does_not_load_chromadb():
    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import sys; import whatwasthat.worker; print('chromadb' in sys.modules)",
        ],
        text=True,
    )

    assert output.strip() == "False"
