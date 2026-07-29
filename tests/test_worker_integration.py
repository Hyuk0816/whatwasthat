from __future__ import annotations

import json
from pathlib import Path

import whatwasthat.config as config_module
from whatwasthat.config import WwtConfig
from whatwasthat.ingest_queue import IngestQueue
from whatwasthat.pipeline.ingest import prepare_transcript, store_prepared_transcript
from whatwasthat.storage.locking import write_lock
from whatwasthat.storage.raw_store import RawSpanStore
from whatwasthat.storage.vector import VectorStore
from whatwasthat.worker import run_worker


def _config(root: Path) -> WwtConfig:
    data_dir = root / "data"
    return WwtConfig(
        home_dir=root,
        data_dir=data_dir,
        chroma_path=data_dir / "vector",
        raw_spans_path=data_dir / "raw" / "spans.db",
        bm25_index_path=data_dir / "bm25" / "index.pkl",
        bm25_version_path=data_dir / "bm25" / "version.txt",
        ingest_queue_path=data_dir / "queue" / "jobs.db",
        worker_lock_path=data_dir / "worker.lock",
    )


def _select_bm25_paths(config: WwtConfig, monkeypatch) -> None:
    monkeypatch.setattr(config_module, "BM25_INDEX_PATH", config.bm25_index_path)
    monkeypatch.setattr(config_module, "BM25_VERSION_PATH", config.bm25_version_path)


def _write_transcript(path: Path) -> None:
    records = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "PostgreSQL을 세션 저장소로 선택한 이유를 정리해 주세요. " * 20,
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": "트랜잭션과 운영 안정성을 기준으로 PostgreSQL을 선택했습니다. " * 20,
            },
        },
    ]
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records))


def test_worker_result_matches_synchronous_ingest_and_is_searchable(tmp_path, monkeypatch):
    transcript = tmp_path / "session.jsonl"
    _write_transcript(transcript)
    prepared = prepare_transcript(transcript)

    sync_config = _config(tmp_path / "sync")
    _select_bm25_paths(sync_config, monkeypatch)
    sync_raw = RawSpanStore(sync_config.raw_spans_path)
    sync_raw.initialize()
    sync_vector = VectorStore(sync_config.chroma_path)
    sync_vector.initialize()
    with write_lock(sync_config.data_dir):
        sync_result = store_prepared_transcript(
            prepared,
            raw_store=sync_raw,
            vector_store=sync_vector,
            rebuild_bm25=True,
        )
    sync_search_ids = [item[0] for item in sync_vector.search("PostgreSQL", top_k=5)]

    worker_config = _config(tmp_path / "worker")
    _select_bm25_paths(worker_config, monkeypatch)
    queue = IngestQueue(worker_config.ingest_queue_path)
    queue.enqueue(transcript, source="codex-cli")
    worker_result = run_worker(
        config=worker_config,
        queue=queue,
        once=True,
        apply_priority=False,
    )
    worker_raw = RawSpanStore(worker_config.raw_spans_path)
    worker_vector = VectorStore(worker_config.chroma_path)
    worker_vector.initialize()
    worker_search_ids = [item[0] for item in worker_vector.search("PostgreSQL", top_k=5)]

    assert worker_result.cycles == 1
    assert queue.list_jobs() == []
    assert worker_vector.count() == sync_result.chunks
    assert len(worker_raw.get_spans_by_session("session")) == sync_result.spans
    assert worker_search_ids == sync_search_ids
    assert worker_search_ids
