"""ChromaDB 벡터 DB 래퍼 - 청크 원문 임베딩, 하이브리드 검색(벡터 + BM25)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi

import whatwasthat.config as _config_module
from whatwasthat.config import EMBEDDING_MODEL
from whatwasthat.embedding import OnnxEmbeddingFunction
from whatwasthat.models import Chunk
from whatwasthat.timeutil import ensure_utc, to_epoch

_log = logging.getLogger("whatwasthat.vector")

# 하이브리드 검색 가중치: vector * α + bm25 * (1-α)
_VECTOR_WEIGHT = 0.6


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


_kiwi = None


def _get_kiwi():
    """Kiwi 형태소 분석기 싱글톤."""
    global _kiwi  # noqa: PLW0603
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def _tokenize(text: str) -> list[str]:
    """한국어 형태소 분석(kiwipiepy) + camelCase 분리 혼합 토크나이저."""
    import re

    # 1차: camelCase 분리 (SheDataset → She Dataset)
    # 소문자→대문자+소문자 경계만 분리 (PostgreSQL의 eS는 분리하지 않음)
    text = re.sub(r"([a-z])([A-Z][a-z])", r"\1 \2", text)
    # 파일 확장자 분리 (file.vue → file vue)
    text = re.sub(r"\.([a-zA-Z]{1,5})\b", r" \1", text)

    # 2차: kiwipiepy 형태소 분석
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)

    # 의미 있는 품사만 추출: 명사(NN*), 영어(SL), 숫자(SN), 동사어간(VV/VA), 어근(XR)
    meaningful = [
        t.form.lower()
        for t in tokens
        if t.tag.startswith(("NN", "NR", "SL", "SN", "VV", "VA", "XR"))
        and len(t.form) > 1
    ]
    return meaningful


class VectorStore:
    """ChromaDB 청크 벡터 검색 + BM25 하이브리드."""

    COLLECTION_NAME = "wwt_chunks"

    def __init__(self, db_path: Path, model_name: str = EMBEDDING_MODEL) -> None:
        self._db_path = db_path
        self._model_name = model_name
        self._client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: list[str] = []
        self._bm25_metas: list[dict] = []
        self._bm25_version_seen: int = 0
        self._project_cache: set[str] | None = None

    def initialize(self) -> None:
        self._db_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._db_path))
        ef = OnnxEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
            embedding_function=ef,
        )
        # 디스크 BM25가 있으면 로드, 없으면 ChromaDB로부터 재빌드
        if not self._try_load_bm25_from_disk():
            self._build_bm25_index()

    def count(self) -> int:
        """저장된 청크 수 반환."""
        return self._get_collection().count()

    def _get_collection(self) -> chromadb.Collection:
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")
        return self._collection

    def _build_bm25_index(self) -> None:
        """ChromaDB에 저장된 문서로 BM25 인덱스 구축."""
        collection = self._get_collection()
        if collection.count() == 0:
            self._bm25 = None
            self._bm25_ids = []
            self._bm25_metas = []
            self._persist_bm25()
            return
        all_data = collection.get(include=["documents", "metadatas"])
        docs = all_data.get("documents") or []
        self._bm25_ids = all_data.get("ids") or []
        self._bm25_metas = all_data.get("metadatas") or []
        tokenized = [_tokenize(doc) for doc in docs]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None
        self._persist_bm25()

    def _persist_bm25(self) -> None:
        """BM25 인덱스를 디스크에 원자적으로 저장 (temp + rename).

        호출 측에서 이미 _write_lock을 보유한 상태에서만 호출되어야 한다.
        """
        bm25_path: Path = _config_module.BM25_INDEX_PATH
        version_path: Path = _config_module.BM25_VERSION_PATH
        bm25_path.parent.mkdir(parents=True, exist_ok=True)

        # 1) 인덱스 파일 atomic write
        tmp_path = bm25_path.with_suffix(".tmp")
        payload = {
            "bm25": self._bm25,
            "ids": self._bm25_ids,
            "metas": self._bm25_metas,
        }
        with open(tmp_path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, bm25_path)  # POSIX atomic rename

        # 2) version 카운터 bump (file write 이후에 해야 reader가 일관성 보장)
        new_version = self._read_bm25_version() + 1
        tmp_v = version_path.with_suffix(".tmp")
        tmp_v.write_text(str(new_version))
        os.replace(tmp_v, version_path)
        self._bm25_version_seen = new_version

    @staticmethod
    def _read_bm25_version() -> int:
        try:
            return int(_config_module.BM25_VERSION_PATH.read_text().strip())
        except (FileNotFoundError, ValueError):
            return 0

    def _try_load_bm25_from_disk(self) -> bool:
        """디스크에서 BM25를 로드. 성공 시 True, 실패/없음 시 False."""
        bm25_path: Path = _config_module.BM25_INDEX_PATH
        if not bm25_path.exists():
            return False
        try:
            with open(bm25_path, "rb") as f:
                payload = pickle.load(f)
            self._bm25 = payload["bm25"]
            self._bm25_ids = payload["ids"]
            self._bm25_metas = payload["metas"]
            self._bm25_version_seen = self._read_bm25_version()
            return True
        except Exception:
            # 손상되었거나 호환 불가 — 재빌드로 fallback
            return False

    def _maybe_reload_bm25(self) -> None:
        """디스크 version이 메모리 캐시보다 새것이면 reload — cross-process freshness."""
        disk_version = self._read_bm25_version()
        if disk_version > self._bm25_version_seen:
            old = self._bm25_version_seen
            if self._try_load_bm25_from_disk():
                _log.info(
                    "BM25 reloaded from disk: v%d → v%d",
                    old, self._bm25_version_seen,
                )

    def upsert_chunks(self, chunks: list[Chunk], *, rebuild_bm25: bool = True) -> None:
        if not chunks:
            return
        collection = self._get_collection()
        ids = [c.id for c in chunks]
        documents = [c.search_text for c in chunks]
        metadatas = [
            {
                "session_id": c.session_id,
                "project": c.project,
                "project_path": c.project_path,
                "git_branch": c.git_branch,
                "env": c.env,
                "chunk_index": c.start_turn_index,  # 세션 내 시작 턴 인덱스
                "start_turn_index": c.start_turn_index,
                "end_turn_index": c.end_turn_index,
                "turn_count": c.turn_count,
                "span_id": c.span_id,
                "granularity": c.granularity,
                "raw_preview": c.raw_preview,
                "raw_length": c.raw_length,
                "content_hash": _content_hash(c.search_text),
                "snippet_ids": json.dumps(c.snippet_ids, ensure_ascii=False),
                "source": c.source,
                "timestamp": (
                    ensure_utc(c.timestamp).isoformat() if c.timestamp else ""
                ),
                # epoch int for native ChromaDB $gte/$lt where-clause range queries
                "timestamp_epoch": to_epoch(c.timestamp),
                "has_code": "true" if c.code_count else "false",
                "code_count": c.code_count,
                "code_languages": ",".join(c.code_languages),
                "access_count": c.access_count,  # Spaced Repetition 감쇠율 조절용
            }
            for c in chunks
        ]
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        self._project_cache = None  # 프로젝트 캐시 무효화
        if rebuild_bm25:
            self._build_bm25_index()

    def rebuild_index(self) -> None:
        """BM25 인덱스 수동 재구축 — 대량 적재 후 호출."""
        self._build_bm25_index()

    def upsert_session_chunks(
        self, session_id: str, chunks: list[Chunk], *, rebuild_bm25: bool = True,
    ) -> int:
        """세션 단위 증분 upsert — 변경된 청크만 임베딩, 오래된 중복 정리.

        Args:
            rebuild_bm25: False면 BM25 재구축 지연 (대량 적재 시 마지막에 rebuild_index() 호출).

        Returns:
            실제로 임베딩된 청크 수.
        """
        if not chunks:
            return 0

        collection = self._get_collection()

        # 1. 이 세션의 기존 청크 메타 조회
        existing = collection.get(
            where={"session_id": session_id},
            include=["metadatas"],
        )
        existing_meta: dict[str, tuple[int, int, str, str]] = {
            cid: (
                int(meta.get("turn_count", 0) or 0),
                int(meta.get("raw_length", 0) or 0),
                str(meta.get("span_id", "") or ""),
                str(meta.get("content_hash", "") or ""),
            ) if meta else (0, 0, "", "")
            for cid, meta in zip(existing["ids"], existing["metadatas"] or [])
        }

        # 2. 새 청크 ID 집합과 비교하여 stale 항목 삭제 (랜덤 UUID 중복 정리)
        new_ids = {c.id for c in chunks}
        stale_ids = [cid for cid in existing_meta if cid not in new_ids]
        if stale_ids:
            collection.delete(ids=stale_ids)

        # 3. 변경된 청크만 필터 — ID 동일 + turn_count 동일이면 스킵
        changed: list[Chunk] = []
        for chunk in chunks:
            old_shape = existing_meta.get(chunk.id)
            new_shape = (
                chunk.turn_count,
                chunk.raw_length,
                chunk.span_id,
                _content_hash(chunk.search_text),
            )
            if old_shape is not None and old_shape == new_shape:
                continue  # 내용 동일, 임베딩 스킵
            changed.append(chunk)

        # 4. 변경분만 upsert (임베딩은 여기서만 발생)
        if changed:
            self.upsert_chunks(changed, rebuild_bm25=rebuild_bm25)
        elif stale_ids:
            # stale 삭제만 했으면 BM25 재구축 필요
            self._build_bm25_index()

        return len(changed)

    def increment_access_counts(self, chunk_ids: list[str]) -> None:
        """주어진 청크들의 access_count를 +1 증가 (Spaced Repetition).

        중복된 ID는 중복만큼 증가 (예: [c1, c1] → c1 +2).
        존재하지 않는 ID는 무시.
        """
        if not chunk_ids:
            return
        from collections import Counter

        collection = self._get_collection()

        # 증가분 집계 — 같은 ID가 여러 번 등장하면 합산
        deltas = Counter(chunk_ids)
        unique_ids = list(deltas.keys())

        # 현재 메타 조회
        current = collection.get(ids=unique_ids, include=["metadatas"])
        if not current["ids"]:
            return

        # access_count만 변경한 새 메타 구성
        new_metas: list[dict] = []
        updated_ids: list[str] = []
        for cid, meta in zip(current["ids"], current["metadatas"]):
            if meta is None:
                continue
            new_meta = dict(meta)
            old_count = int(new_meta.get("access_count", 0) or 0)
            new_meta["access_count"] = old_count + deltas[cid]
            new_metas.append(new_meta)
            updated_ids.append(cid)

        if updated_ids:
            collection.update(ids=updated_ids, metadatas=new_metas)

    def _resolve_project(self, project: str) -> str:
        """프로젝트명 퍼지 매칭 — 정확한 이름을 몰라도 찾아줌."""
        collection = self._get_collection()
        if collection.count() == 0:
            return project

        # 캐시된 프로젝트 목록 사용
        if self._project_cache is None:
            all_data = collection.get(include=["metadatas"])
            self._project_cache = {
                m.get("project", "")
                for m in (all_data["metadatas"] or [])
                if m and m.get("project")
            }
        projects = self._project_cache

        # 1. 정확한 매칭
        if project in projects:
            return project

        # 2. 대소문자 무시 매칭
        lower = project.lower()
        for p in projects:
            if p.lower() == lower:
                return p

        # 3. 정규화 매칭 (_, -, 공백 제거 후 비교)
        normalized = lower.replace("_", "").replace("-", "").replace(" ", "")
        for p in projects:
            p_norm = p.lower().replace("_", "").replace("-", "").replace(" ", "")
            if normalized == p_norm:
                return p

        # 4. 부분 문자열 매칭 (한쪽이 다른 쪽을 포함)
        for p in projects:
            p_norm = p.lower().replace("_", "").replace("-", "").replace(" ", "")
            if normalized in p_norm or p_norm in normalized:
                return p

        return project

    def search(
        self,
        query: str,
        top_k: int = 10,
        project: str | None = None,
        env: str | None = None,
        source: str | None = None,
        git_branch: str | None = None,
        since_epoch: int | None = None,
        until_epoch: int | None = None,
    ) -> list[tuple[str, float, dict]]:
        # cross-process freshness — 다른 프로세스가 BM25를 갱신했으면 reload
        self._maybe_reload_bm25()
        collection = self._get_collection()
        if collection.count() == 0:
            return []

        # 프로젝트명 퍼지 매칭
        if project:
            project = self._resolve_project(project)

        # 후보 풀 크기 — 벡터/BM25 각각 top_k*3을 가져와서 합집합
        candidate_k = min(top_k * 3, collection.count())

        # 1. 벡터 검색
        filters: list[dict] = []
        if project:
            filters.append({"project": project})
        if env:
            filters.append({"env": env})
        if source:
            filters.append({"source": source})
        if git_branch:
            filters.append({"git_branch": git_branch})
        if since_epoch is not None:
            filters.append({"timestamp_epoch": {"$gte": since_epoch}})
        if until_epoch is not None:
            filters.append({"timestamp_epoch": {"$lt": until_epoch}})

        if len(filters) > 1:
            where = {"$and": filters}
        elif len(filters) == 1:
            where = filters[0]
        else:
            where = None
        try:
            vec_results = collection.query(
                query_texts=[query],
                n_results=candidate_k,
                where=where,
                include=["metadatas", "distances"],
            )
        except Exception:
            # ChromaDB HNSW can throw "Error finding id" when internal index
            # references deleted entries while a metadata filter is active.
            # Fallback: query without filter, post-filter in Python below.
            if where is not None:
                _log.warning(
                    "ChromaDB query failed with where=%s, retrying without filter",
                    where,
                )
                vec_results = collection.query(
                    query_texts=[query],
                    n_results=candidate_k,
                    where=None,
                    include=["metadatas", "distances"],
                )
            else:
                raise  # no filter to drop — genuine error

        vec_scores: dict[str, float] = {}
        vec_metas: dict[str, dict] = {}
        _active_filters = {
            "project": project,
            "env": env,
            "source": source,
            "git_branch": git_branch,
        }
        if vec_results["ids"] and vec_results["distances"]:
            for chunk_id, distance, meta in zip(
                vec_results["ids"][0],
                vec_results["distances"][0],
                vec_results["metadatas"][0],
            ):
                # Post-filter: when fallback dropped the where clause,
                # enforce filters in Python so results stay correct.
                if any(
                    v is not None and meta.get(k) != v
                    for k, v in _active_filters.items()
                ):
                    continue
                # Epoch range post-filter (for fallback path where where=None)
                ep = int(meta.get("timestamp_epoch", 0) or 0)
                if since_epoch is not None and ep < since_epoch:
                    continue
                if until_epoch is not None and ep >= until_epoch:
                    continue
                vec_scores[chunk_id] = max(0.0, 1.0 - distance)
                vec_metas[chunk_id] = meta

        # 2. BM25 검색 — 상위 candidate_k개만 사용
        bm25_scores: dict[str, float] = {}
        if self._bm25 and self._bm25_ids:
            query_tokens = _tokenize(query)
            if query_tokens:
                raw_scores = self._bm25.get_scores(query_tokens)
                max_bm25 = max(raw_scores) if max(raw_scores) > 0 else 1.0
                import numpy as np
                top_indices = np.argsort(raw_scores)[-candidate_k:][::-1]
                for idx in top_indices:
                    score = raw_scores[idx]
                    if score <= 0:
                        break
                    cid = self._bm25_ids[idx]
                    meta = self._bm25_metas[idx] if idx < len(self._bm25_metas) else {}
                    if project and meta.get("project") != project:
                        continue
                    if env and meta.get("env") != env:
                        continue
                    if source and meta.get("source") != source:
                        continue
                    if git_branch and meta.get("git_branch") != git_branch:
                        continue
                    # Epoch range filter
                    ep = int(meta.get("timestamp_epoch", 0) or 0)
                    if since_epoch is not None and ep < since_epoch:
                        continue
                    if until_epoch is not None and ep >= until_epoch:
                        continue
                    bm25_scores[cid] = score / max_bm25
                    if cid not in vec_metas:
                        vec_metas[cid] = meta

        # 3. 하이브리드 점수 결합 — 합집합의 양쪽 점수 결합
        all_ids = set(vec_scores.keys()) | set(bm25_scores.keys())
        combined: list[tuple[str, float, dict]] = []
        for cid in all_ids:
            v_score = vec_scores.get(cid, 0.0)
            b_score = bm25_scores.get(cid, 0.0)
            hybrid = v_score * _VECTOR_WEIGHT + b_score * (1 - _VECTOR_WEIGHT)
            combined.append((cid, hybrid, vec_metas.get(cid, {})))

        combined.sort(key=lambda x: x[1], reverse=True)
        top_combined = combined[:top_k]

        # Defensive ID filter: ensure every returned ID still exists in ChromaDB.
        # Protects against stale BM25 cache (phantom IDs that were deleted by another
        # process) and ChromaDB internal HNSW staleness across processes.
        if top_combined:
            try:
                existing = collection.get(
                    ids=[cid for cid, _, _ in top_combined],
                    include=[],  # only need IDs
                )
                existing_set = set(existing.get("ids") or [])
                phantoms = [cid for cid, _, _ in top_combined if cid not in existing_set]
                if phantoms:
                    _log.warning(
                        "vector.search dropped %d phantom IDs from BM25/vec results: %s",
                        len(phantoms), phantoms[:5],  # 처음 5개만 로깅
                    )
                top_combined = [
                    (cid, score, meta) for cid, score, meta in top_combined
                    if cid in existing_set
                ]
            except Exception as e:
                _log.exception("Defensive ID filter failed: %s", e)
        return top_combined
