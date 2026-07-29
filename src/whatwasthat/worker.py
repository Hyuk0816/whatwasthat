"""On-demand warm worker for deferred local transcript ingestion."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from whatwasthat.config import WwtConfig
from whatwasthat.ingest_queue import IngestJob, IngestQueue
from whatwasthat.pipeline.ingest import (
    PermanentIngestError,
    PreparedTranscript,
    prepare_transcript,
    store_prepared_transcript,
)
from whatwasthat.storage.locking import InterProcessLock, write_lock

DEFAULT_DEBOUNCE_SECONDS = 15.0
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_IDLE_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_JOBS = 16
DEFAULT_NICE_INCREMENT = 10
DEFAULT_ONNX_THREADS = 1


class _VectorStore(Protocol):
    def rebuild_index(self) -> None: ...


@dataclass(frozen=True)
class WorkerResources:
    raw_store: object
    vector_store: _VectorStore


@dataclass(frozen=True)
class WorkerCycleResult:
    succeeded: int = 0
    transient_failures: int = 0
    permanent_failures: int = 0
    rebuilt_bm25: bool = False


@dataclass(frozen=True)
class WorkerRunResult:
    cycles: int
    already_running: bool = False


def _default_resource_factory(config: WwtConfig) -> WorkerResources:
    from whatwasthat.storage.raw_store import RawSpanStore
    from whatwasthat.storage.vector import VectorStore

    raw_store = RawSpanStore(config.raw_spans_path)
    vector_store = VectorStore(config.chroma_path)
    with write_lock(config.data_dir):
        raw_store.initialize()
        vector_store.initialize()
    return WorkerResources(raw_store=raw_store, vector_store=vector_store)


def append_ingest_log(log_path: Path, message: str) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"{timestamp} {message}\n")


def process_jobs(
    queue: IngestQueue,
    jobs: list[IngestJob],
    *,
    config: WwtConfig,
    resources: WorkerResources | None = None,
    resource_factory: Callable[[], WorkerResources] | None = None,
    prepare: Callable[[Path], PreparedTranscript] = prepare_transcript,
    lock_factory: Callable[[Path], AbstractContextManager[None]] = write_lock,
    log_path: Path | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> WorkerCycleResult:
    """Prepare jobs independently, store valid jobs, then rebuild BM25 once."""
    prepared_jobs: list[tuple[IngestJob, PreparedTranscript]] = []
    permanent_failures = 0
    transient_failures = 0
    succeeded_jobs: list[IngestJob] = []
    failed_jobs: list[tuple[IngestJob, Exception]] = []
    started_at: dict[tuple[Path, int], float] = {}

    def elapsed_ms(job: IngestJob) -> int:
        started = started_at[(job.transcript_path, job.revision)]
        return int((monotonic() - started) * 1000)

    for job in jobs:
        started_at[(job.transcript_path, job.revision)] = monotonic()
        if log_path is not None:
            append_ingest_log(
                log_path,
                f"source={job.source} transcript={job.transcript_path} "
                f"revision={job.revision} status=ingest_start",
            )
        try:
            prepared_jobs.append((job, prepare(job.transcript_path)))
        except PermanentIngestError as exc:
            queue.mark_permanent_failure(job, str(exc))
            permanent_failures += 1
            if log_path is not None:
                append_ingest_log(
                    log_path,
                    f"source={job.source} transcript={job.transcript_path} "
                    f"status=failed permanent=true "
                    f"elapsed_ms={elapsed_ms(job)} "
                    f"error={exc}",
                )
        except Exception as exc:
            failed_jobs.append((job, exc))

    rebuilt = False
    if prepared_jobs:
        try:
            if resources is None:
                if resource_factory is None:
                    raise RuntimeError("worker resources are not configured")
                resources = resource_factory()
            with lock_factory(config.data_dir):
                for job, prepared in prepared_jobs:
                    try:
                        store_prepared_transcript(
                            prepared,
                            raw_store=resources.raw_store,  # type: ignore[arg-type]
                            vector_store=resources.vector_store,  # type: ignore[arg-type]
                            rebuild_bm25=False,
                        )
                        succeeded_jobs.append(job)
                    except Exception as exc:
                        failed_jobs.append((job, exc))
                if succeeded_jobs:
                    resources.vector_store.rebuild_index()
                    rebuilt = True
        except Exception as exc:
            failed_jobs.extend((job, exc) for job in succeeded_jobs)
            succeeded_jobs = []
            rebuilt = False

    for job in succeeded_jobs:
        acknowledged = queue.acknowledge(job)
        if log_path is not None:
            status = "ingest_done" if acknowledged else "ingest_superseded"
            append_ingest_log(
                log_path,
                f"source={job.source} transcript={job.transcript_path} status={status} "
                f"elapsed_ms={elapsed_ms(job)}",
            )

    for job, exc in failed_jobs:
        state = queue.mark_transient_failure(job, str(exc))
        if state != "superseded":
            transient_failures += 1
        if log_path is not None:
            status = (
                "ingest_superseded"
                if state == "superseded"
                else "failed" if state == "failed" else "retry"
            )
            append_ingest_log(
                log_path,
                f"source={job.source} transcript={job.transcript_path} "
                f"status={status} "
                f"elapsed_ms={elapsed_ms(job)} "
                f"error={exc}",
            )

    return WorkerCycleResult(
        succeeded=len(succeeded_jobs),
        transient_failures=transient_failures,
        permanent_failures=permanent_failures,
        rebuilt_bm25=rebuilt,
    )


def run_worker(
    *,
    config: WwtConfig | None = None,
    queue: IngestQueue | None = None,
    once: bool = False,
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
    max_jobs: int = DEFAULT_MAX_JOBS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    resource_factory: Callable[[WwtConfig], WorkerResources] = _default_resource_factory,
    prepare: Callable[[Path], PreparedTranscript] = prepare_transcript,
    apply_priority: bool = True,
) -> WorkerRunResult:
    """Drain ready jobs with one warm storage/model instance."""
    resolved_config = config or WwtConfig()
    resolved_queue = queue or IngestQueue(resolved_config.ingest_queue_path)
    resolved_queue.initialize()
    worker_lock = InterProcessLock(resolved_config.worker_lock_path)
    if not worker_lock.acquire(blocking=False):
        return WorkerRunResult(cycles=0, already_running=True)

    log_path = resolved_config.home_dir / "ingest.log"
    if apply_priority:
        try:
            os.nice(DEFAULT_NICE_INCREMENT)
        except OSError:
            pass
    os.environ.setdefault("WWT_ONNX_THREADS", str(DEFAULT_ONNX_THREADS))
    append_ingest_log(log_path, "source=worker status=worker_start")

    resources: WorkerResources | None = None
    cycles = 0
    last_activity = monotonic()
    effective_debounce = 0.0 if once else max(0.0, debounce_seconds)

    try:
        while True:
            jobs = resolved_queue.ready(
                debounce_seconds=effective_debounce,
                limit=max(1, max_jobs),
            )
            if jobs:
                def get_resources() -> WorkerResources:
                    nonlocal resources
                    if resources is None:
                        resources = resource_factory(resolved_config)
                    return resources

                process_jobs(
                    resolved_queue,
                    jobs,
                    config=resolved_config,
                    resources=resources,
                    resource_factory=get_resources,
                    prepare=prepare,
                    log_path=log_path,
                    monotonic=monotonic,
                )
                cycles += 1
                last_activity = monotonic()
                continue

            if once:
                break

            if monotonic() - last_activity >= idle_timeout_seconds:
                with resolved_queue.immediate_transaction() as conn:
                    if resolved_queue.pending_in_transaction(conn):
                        last_activity = monotonic()
                    else:
                        worker_lock.release()
                        append_ingest_log(log_path, "source=worker status=worker_idle_exit")
                        return WorkerRunResult(cycles=cycles)
                continue
            sleep(max(0.0, poll_seconds))
    finally:
        worker_lock.release()
    return WorkerRunResult(cycles=cycles)


def worker_is_running(lock_path: Path) -> bool:
    probe = InterProcessLock(lock_path)
    if not probe.acquire(blocking=False):
        return True
    probe.release()
    return False


def spawn_worker(config: WwtConfig) -> bool:
    """Start a detached worker candidate if no worker currently owns the lock."""
    if worker_is_running(config.worker_lock_path):
        return False
    log_path = config.home_dir / "ingest.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    env = os.environ.copy()
    env["WWT_HOME"] = str(config.home_dir)
    env.setdefault("WWT_ONNX_THREADS", str(DEFAULT_ONNX_THREADS))
    try:
        subprocess.Popen(
            [sys.executable, "-m", "whatwasthat.worker"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=env,
        )
    finally:
        log_file.close()
    return True


def main() -> None:
    run_worker()


if __name__ == "__main__":
    main()
