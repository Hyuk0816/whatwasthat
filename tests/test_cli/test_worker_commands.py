from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from whatwasthat.config import WwtConfig
from whatwasthat.ingest_queue import IngestQueue
from whatwasthat.worker import WorkerRunResult


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


def test_enqueue_command_persists_job_and_requests_worker(tmp_data_dir, monkeypatch):
    import whatwasthat.cli.app as app_module
    import whatwasthat.worker as worker_module

    config = _config(tmp_data_dir)
    transcript = tmp_data_dir / "session.jsonl"
    transcript.write_text(json.dumps({"type": "user"}) + "\n")
    started: list[Path] = []
    monkeypatch.setattr(app_module, "_get_config", lambda: config)
    monkeypatch.setattr(
        worker_module,
        "spawn_worker",
        lambda received: started.append(received.worker_lock_path) or True,
    )

    result = CliRunner().invoke(
        app_module.app,
        ["enqueue", str(transcript), "--source", "codex-cli"],
    )

    assert result.exit_code == 0, result.output
    jobs = IngestQueue(config.ingest_queue_path).list_jobs()
    assert len(jobs) == 1
    assert jobs[0].transcript_path == transcript
    assert jobs[0].source == "codex-cli"
    assert started == [config.worker_lock_path]
    assert "worker=started" in result.output


def test_queue_status_reports_failed_job(tmp_data_dir, monkeypatch):
    import whatwasthat.cli.app as app_module

    config = _config(tmp_data_dir)
    queue = IngestQueue(config.ingest_queue_path)
    job = queue.enqueue(tmp_data_dir / "missing.jsonl", source="gemini-cli")
    queue.mark_permanent_failure(job, "transcript does not exist")
    monkeypatch.setattr(app_module, "_get_config", lambda: config)

    result = CliRunner().invoke(app_module.app, ["queue-status"])

    assert result.exit_code == 0
    assert "pending=0 failed=1" in result.output
    assert "attempts=1" in result.output
    assert "transcript does not exist" in result.output


def test_queue_status_reports_pending_retry_details(tmp_data_dir, monkeypatch):
    import whatwasthat.cli.app as app_module

    config = _config(tmp_data_dir)
    queue = IngestQueue(config.ingest_queue_path)
    job = queue.enqueue(tmp_data_dir / "retry.jsonl", source="claude-code")
    queue.mark_transient_failure(job, "database busy")
    monkeypatch.setattr(app_module, "_get_config", lambda: config)

    result = CliRunner().invoke(app_module.app, ["queue-status"])

    assert result.exit_code == 0
    assert "pending=1 failed=0" in result.output
    assert "pending path=" in result.output
    assert "attempts=1" in result.output
    assert "error=database busy" in result.output


def test_worker_once_forwards_runtime_options(tmp_data_dir, monkeypatch):
    import whatwasthat.cli.app as app_module
    import whatwasthat.worker as worker_module

    config = _config(tmp_data_dir)
    received: dict = {}
    monkeypatch.setattr(app_module, "_get_config", lambda: config)

    def fake_run_worker(**kwargs):
        received.update(kwargs)
        return WorkerRunResult(cycles=2)

    monkeypatch.setattr(worker_module, "run_worker", fake_run_worker)
    result = CliRunner().invoke(
        app_module.app,
        [
            "worker",
            "--once",
            "--debounce", "3",
            "--poll", "0.2",
            "--idle-timeout", "9",
            "--max-jobs", "4",
        ],
    )

    assert result.exit_code == 0, result.output
    assert received["once"] is True
    assert received["debounce_seconds"] == 3.0
    assert received["poll_seconds"] == 0.2
    assert received["idle_timeout_seconds"] == 9.0
    assert received["max_jobs"] == 4
    assert "2 cycle(s)" in result.output


def test_reset_refuses_while_worker_is_running(tmp_data_dir, monkeypatch):
    import whatwasthat.cli.app as app_module
    from whatwasthat.storage.locking import InterProcessLock

    config = _config(tmp_data_dir)
    config.chroma_path.mkdir(parents=True)
    marker = config.chroma_path / "keep"
    marker.write_text("data")
    monkeypatch.setattr(app_module, "_get_config", lambda: config)
    held_lock = InterProcessLock(config.worker_lock_path)
    assert held_lock.acquire(blocking=False)

    try:
        result = CliRunner().invoke(app_module.app, ["reset", "--force"])
    finally:
        held_lock.release()

    assert result.exit_code == 1
    assert "Worker is running" in result.output
    assert marker.exists()


def test_reset_removes_queue_together_with_search_data(tmp_data_dir, monkeypatch):
    import whatwasthat.cli.app as app_module

    config = _config(tmp_data_dir)
    config.chroma_path.mkdir(parents=True)
    (config.chroma_path / "vector-data").write_text("data")
    queue = IngestQueue(config.ingest_queue_path)
    queue.enqueue(tmp_data_dir / "session.jsonl", source="codex-cli")
    monkeypatch.setattr(app_module, "_get_config", lambda: config)

    result = CliRunner().invoke(app_module.app, ["reset", "--force"])

    assert result.exit_code == 0, result.output
    assert not config.chroma_path.exists()
    assert not config.ingest_queue_path.parent.exists()
    assert "vector + raw + bm25 + queue" in result.output
