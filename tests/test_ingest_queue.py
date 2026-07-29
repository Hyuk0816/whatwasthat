from __future__ import annotations

import multiprocessing
from pathlib import Path

from whatwasthat.ingest_queue import IngestQueue


def _enqueue_in_subprocess(db_path: str, transcript_path: str, started, finished) -> None:
    started.set()
    IngestQueue(Path(db_path)).enqueue(Path(transcript_path), source="codex-cli")
    finished.set()


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_enqueue_coalesces_path_and_resets_failed_revision(tmp_data_dir: Path):
    clock = FakeClock()
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db", clock=clock)
    path = tmp_data_dir / "session.jsonl"

    first = queue.enqueue(path, source="codex-cli")
    queue.mark_permanent_failure(first, "invalid transcript")
    clock.advance(1)
    second = queue.enqueue(path, source="claude-code")

    jobs = queue.list_jobs()
    assert len(jobs) == 1
    assert second.revision == 2
    assert jobs[0].source == "claude-code"
    assert jobs[0].state == "pending"
    assert jobs[0].attempts == 0
    assert jobs[0].last_error is None


def test_acknowledge_does_not_delete_newer_revision(tmp_data_dir: Path):
    clock = FakeClock()
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db", clock=clock)
    path = tmp_data_dir / "session.jsonl"
    first = queue.enqueue(path, source="codex-cli")
    clock.advance(1)
    second = queue.enqueue(path, source="codex-cli")

    assert queue.acknowledge(first) is False
    assert queue.list_jobs() == [second]
    assert queue.acknowledge(second) is True
    assert queue.list_jobs() == []


def test_transient_failure_uses_five_and_thirty_second_retries(tmp_data_dir: Path):
    clock = FakeClock()
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db", clock=clock)
    job = queue.enqueue(tmp_data_dir / "session.jsonl", source="codex-cli")

    assert queue.mark_transient_failure(job, "busy") == "pending"
    retry_one = queue.list_jobs()[0]
    assert retry_one.attempts == 1
    assert retry_one.next_attempt_at == 105.0
    assert queue.ready(debounce_seconds=0, limit=1) == []

    clock.advance(5)
    assert queue.ready(debounce_seconds=0, limit=1) == [retry_one]
    assert queue.mark_transient_failure(retry_one, "busy again") == "pending"
    retry_two = queue.list_jobs()[0]
    assert retry_two.attempts == 2
    assert retry_two.next_attempt_at == 135.0

    clock.advance(30)
    assert queue.mark_transient_failure(retry_two, "still busy") == "failed"
    failed = queue.list_jobs()[0]
    assert failed.attempts == 3
    assert failed.state == "failed"
    assert queue.ready(debounce_seconds=0, limit=1) == []


def test_ready_respects_debounce_and_limit(tmp_data_dir: Path):
    clock = FakeClock()
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db", clock=clock)
    first = queue.enqueue(tmp_data_dir / "a.jsonl", source="codex-cli")
    clock.advance(5)
    queue.enqueue(tmp_data_dir / "b.jsonl", source="gemini-cli")

    assert queue.ready(debounce_seconds=15, limit=16) == []
    clock.advance(10)
    assert queue.ready(debounce_seconds=15, limit=1) == [first]


def test_summary_reports_pending_and_recent_failures(tmp_data_dir: Path):
    clock = FakeClock()
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db", clock=clock)
    pending = queue.enqueue(tmp_data_dir / "pending.jsonl", source="codex-cli")
    clock.advance(1)
    failed = queue.enqueue(tmp_data_dir / "failed.jsonl", source="gemini-cli")
    queue.mark_permanent_failure(failed, "missing")

    summary = queue.summary()
    assert summary.pending == 1
    assert summary.failed == 1
    assert summary.oldest_pending_at == pending.enqueued_at
    assert summary.recent_errors[0].last_error == "missing"


def test_final_empty_transaction_serializes_a_concurrent_enqueue(tmp_data_dir: Path):
    queue = IngestQueue(tmp_data_dir / "queue" / "jobs.db")
    queue.initialize()
    context = multiprocessing.get_context("spawn")
    enqueue_started = context.Event()
    enqueue_finished = context.Event()
    producer = context.Process(
        target=_enqueue_in_subprocess,
        args=(
            str(queue.db_path),
            str(tmp_data_dir / "late.jsonl"),
            enqueue_started,
            enqueue_finished,
        ),
    )
    with queue.immediate_transaction() as conn:
        assert queue.pending_in_transaction(conn) is False
        producer.start()
        assert enqueue_started.wait(timeout=1)
        assert enqueue_finished.wait(timeout=0.05) is False

    assert enqueue_finished.wait(timeout=1)
    producer.join(timeout=1)
    assert producer.exitcode == 0
    assert queue.has_pending() is True
