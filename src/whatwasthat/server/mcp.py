"""WWT MCP 서버 — Claude Code/Desktop에서 대화 기억 검색."""

from __future__ import annotations

import fcntl
import time
from typing import IO

from mcp.server.fastmcp import FastMCP

import whatwasthat.config as _config_module
from whatwasthat.config import WwtConfig
from whatwasthat.models import SearchResult
from whatwasthat.search.engine import SearchEngine
from whatwasthat.storage.vector import VectorStore

def _format_timestamp(result: SearchResult) -> str:
    """검색 결과의 타임스탬프를 읽기 좋은 문자열로 포맷."""
    if result.started_at is None:
        return ""
    return f" @ {result.started_at.strftime('%Y-%m-%d %H:%M')}"


mcp = FastMCP(
    "whatwasthat",
    instructions=(
        "세션 시작 시, 현재 프로젝트의 최근 기술 결정사항을 검색하여 컨텍스트를 파악하세요. "
        "search_memory(query='recent technical decisions and architecture choices')를 호출하세요. "
        "사용자가 과거 대화, 이전 작업, 의사결정 이유를 물을 때도 이 도구를 사용하세요. "
        "예: '그때 그거 뭐였지?', '이전에 어떻게 했지?', '왜 Redis를 선택했지?' 등. "
        "search_memory는 현재 프로젝트 맥락으로, search_all은 모든 프로젝트에서, "
        "search_decision은 의사결정 맥락(왜 A 대신 B를 선택했는지)을 검색합니다."
    ),
)


_engine: SearchEngine | None = None
_lock_fd: IO[str] | None = None  # 프로세스 수명 동안 락 유지


def _get_engine() -> SearchEngine:
    """SearchEngine 싱글톤 — 파일 락으로 다중 인스턴스 보호."""
    global _engine, _lock_fd  # noqa: PLW0603
    if _engine is None:
        # 모듈 변수를 직접 읽어 monkeypatch가 반영되도록 함
        data_dir = _config_module.WWT_DATA_DIR
        chroma_path = _config_module.CHROMA_DB_PATH
        data_dir.mkdir(parents=True, exist_ok=True)

        # 파일 락 — 프로세스 종료 시 자동 해제
        lock_path = data_dir / "wwt.lock"
        _lock_fd = open(lock_path, "w")  # noqa: SIM115
        for attempt in range(5):
            try:
                fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if attempt == 4:
                    # 5회 실패 시 공유 락으로 읽기 전용 모드
                    fcntl.flock(_lock_fd, fcntl.LOCK_SH)
                    break
                time.sleep(1)

        vector = VectorStore(chroma_path)
        vector.initialize()
        _engine = SearchEngine(vector=vector)
    return _engine


def _reset_engine() -> None:
    """테스트용 싱글톤 리셋."""
    global _engine, _lock_fd  # noqa: PLW0603
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        except OSError:
            pass
        _lock_fd = None
    _engine = None


@mcp.tool()
def search_memory(
    query: str,
    project: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
    git_branch: str | None = None,
) -> str:
    """프로젝트, 플랫폼, 브랜치 등 특정 조건으로 과거 대화를 검색합니다.

    사용자가 특정 프로젝트, 플랫폼(Claude/Gemini/Codex),
    또는 브랜치를 언급하면 이 도구를 사용하세요.

    Args:
        query: 검색할 내용 (예: "DB 뭘로 했지?", "Redis 캐시 설정")
        project: 특정 프로젝트명으로 필터링 (예: "whatwasthat", "frontend")
        cwd: 현재 작업 디렉토리 (자동 감지용, project 미지정 시 프로젝트명 추출에 사용)
        source: 플랫폼 필터 — "claude-code" (클로드),
            "gemini-cli" (제미나이), "codex-cli" (코덱스)
        git_branch: 특정 Git 브랜치로 필터링 (예: "main", "feature/auth")
    """
    engine = _get_engine()

    # 프로젝트 필터 결정: 명시적 project > cwd에서 추출 > 전체 검색
    # 단, source나 git_branch가 명시되면 크로스 프로젝트 검색 의도이므로 cwd 자동 필터 생략
    filter_project = project
    if not filter_project and cwd and not source and not git_branch:
        filter_project = cwd.rstrip("/").split("/")[-1]

    results = engine.search(query, project=filter_project, source=source, git_branch=git_branch)

    if not results:
        return "관련 기억을 찾지 못했습니다."

    lines: list[str] = []
    lines.append(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")

    for i, result in enumerate(results, 1):
        branch = f" ({result.git_branch})" if result.git_branch else ""
        source_tag = f" [{result.source}]" if result.source else ""
        ts = _format_timestamp(result)
        lines.append(f"{i}. {result.project}{branch}{source_tag}{ts} (점수: {result.score:.2f})")
        for chunk in result.chunks[:3]:
            for line in chunk.raw_text.strip().split("\n")[:3]:
                lines.append(f"   {line[:120]}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_all(query: str) -> str:
    """특정 프로젝트, 플랫폼, 브랜치를 언급하지 않고 과거 대화를 검색할 때 사용합니다.
    모든 프로젝트, 모든 플랫폼에서 통합 검색합니다.

    Args:
        query: 검색할 내용 (예: "전에 했던 Redis 설정", "비슷한 버그 해결")
    """
    engine = _get_engine()
    results = engine.search(query, project=None)

    if not results:
        return "관련 기억을 찾지 못했습니다."

    lines: list[str] = []
    lines.append(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")

    for i, result in enumerate(results, 1):
        branch = f" ({result.git_branch})" if result.git_branch else ""
        source_tag = f" [{result.source}]" if result.source else ""
        ts = _format_timestamp(result)
        lines.append(f"{i}. {result.project}{branch}{source_tag}{ts} (점수: {result.score:.2f})")
        for chunk in result.chunks[:2]:
            for line in chunk.raw_text.strip().split("\n")[:2]:
                lines.append(f"   {line[:120]}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_decision(
    query: str,
    project: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
    git_branch: str | None = None,
) -> str:
    """의사결정 맥락을 검색합니다. '왜 A 대신 B를 선택했지?' 같은 질문에 사용하세요.

    Args:
        query: 의사결정 검색 쿼리 (예: "왜 Redis를 선택했지?", "DB를 바꾼 이유")
        project: 특정 프로젝트명으로 필터링
        cwd: 현재 작업 디렉토리 (자동 감지용, project 미지정 시 프로젝트명 추출에 사용)
        source: 플랫폼 필터 — "claude-code", "gemini-cli", "codex-cli"
        git_branch: 특정 Git 브랜치로 필터링
    """
    engine = _get_engine()

    filter_project = project
    if not filter_project and cwd and not source and not git_branch:
        filter_project = cwd.rstrip("/").split("/")[-1]

    results = engine.search(
        query, project=filter_project, source=source, git_branch=git_branch, mode="decision",
    )

    if not results:
        return "관련 의사결정 기억을 찾지 못했습니다."

    lines: list[str] = []
    lines.append(f"{len(results)}개 세션에서 의사결정 기억을 찾았습니다:\n")

    for i, result in enumerate(results, 1):
        branch = f" ({result.git_branch})" if result.git_branch else ""
        source_tag = f" [{result.source}]" if result.source else ""
        ts = _format_timestamp(result)
        lines.append(f"{i}. {result.project}{branch}{source_tag}{ts} (점수: {result.score:.2f})")
        for chunk in result.chunks[:3]:
            for line in chunk.raw_text.strip().split("\n")[:3]:
                lines.append(f"   {line[:120]}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def ingest_session(path: str) -> str:
    """JSONL 대화 로그를 벡터 DB에 적재합니다.

    Args:
        path: JSONL 파일 또는 디렉토리 경로
    """
    from pathlib import Path

    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import detect_parser

    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    vector = VectorStore(config.chroma_path)
    vector.initialize()

    file_path = Path(path).expanduser()
    if file_path.is_dir():
        sessions: dict[str, list] = {}
        meta_map: dict = {}
        for f in sorted(file_path.rglob("*")):
            if f.is_file() and f.suffix in (".jsonl", ".json"):
                parser = detect_parser(f)
                if parser is None:
                    continue
                sid = f.stem
                turns = parser.parse_turns(f)
                if turns:
                    sessions[sid] = turns
                    meta_map[sid] = parser.parse_meta(f)
    else:
        parser = detect_parser(file_path)
        if parser is None:
            return f"지원하지 않는 파일 형식: {file_path}"
        sid = file_path.stem
        sessions = {sid: parser.parse_turns(file_path)}
        meta_map = {sid: parser.parse_meta(file_path)}

    total_chunks = 0
    total_embedded = 0
    for session_id, turns in sessions.items():
        if not turns:
            continue
        meta = meta_map.get(session_id)
        chunks = chunk_turns(turns, session_id=session_id, meta=meta)
        if chunks:
            embedded = vector.upsert_session_chunks(session_id, chunks)
            total_chunks += len(chunks)
            total_embedded += embedded

    # 적재 후 싱글톤 BM25 갱신
    if _engine is not None:
        _engine._vector.rebuild_index()

    return f"완료: {len(sessions)} 세션, {total_chunks} 청크 ({total_embedded} 신규 임베딩)"


@mcp.resource("wwt://project/{project}/context")
def project_context(project: str) -> str:
    """프로젝트의 최근 의사결정 맥락 요약 (최대 2000토큰 이내)."""
    engine = _get_engine()
    results = engine.search(
        "기술 결정 선택 아키텍처 설정 decided chose architecture",
        project=project,
        top_k=5,
        mode="decision",
    )
    if not results:
        return f"{project}: 저장된 의사결정 맥락 없음"

    lines: list[str] = [f"# {project} — 최근 의사결정 맥락\n"]
    total_len = 0
    for r in results[:3]:
        snippet = r.summary[:200]
        total_len += len(snippet)
        if total_len > 1500:
            break
        lines.append(f"- {snippet}")
        lines.append("")

    return "\n".join(lines)
