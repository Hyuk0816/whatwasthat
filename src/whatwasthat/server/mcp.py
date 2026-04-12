"""WWT MCP 서버 — Claude Code/Desktop에서 대화 기억 검색."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager

from mcp.server.fastmcp import FastMCP

import whatwasthat.config as _config_module
from whatwasthat.models import SearchResult
from whatwasthat.search.engine import SearchEngine
from whatwasthat.storage.raw_store import RawSpanStore
from whatwasthat.storage.vector import VectorStore
from whatwasthat.timeutil import format_kst
from whatwasthat.usage_guide import USAGE_GUIDE_INLINE


def _format_timestamp(result: SearchResult) -> str:
    """검색 결과의 타임스탬프를 읽기 좋은 문자열로 포맷."""
    if result.started_at is None:
        return ""
    return f" @ {format_kst(result.started_at)}"


mcp = FastMCP(
    "whatwasthat",
    instructions=USAGE_GUIDE_INLINE,
)


_engine: SearchEngine | None = None
_raw_store: RawSpanStore | None = None


def _get_engine() -> SearchEngine:
    """SearchEngine 싱글톤 — 진짜 읽기 전용 (v1.0.11.2부터).

    v1.0.11.1까지 search 경로는 Spaced Repetition으로 access_count 쓰기를
    부수효과로 수행했고, 멀티 프로세스 환경에서 ChromaDB 커넥션 라우팅
    이슈로 SQLITE_READONLY를 유발했다. v1.0.11.2에서 이 쓰기를 search에서
    완전히 제거. access_count 증가는 v1.0.12의 recall_chunk(expansion 경로)
    에서만 발생할 예정.
    """
    global _engine  # noqa: PLW0603
    if _engine is None:
        data_dir = _config_module.WWT_DATA_DIR
        chroma_path = _config_module.CHROMA_DB_PATH
        data_dir.mkdir(parents=True, exist_ok=True)

        vector = VectorStore(chroma_path)
        vector.initialize()
        _engine = SearchEngine(vector=vector)
    return _engine


def _get_raw_store() -> RawSpanStore:
    """RawSpanStore 싱글톤."""
    global _raw_store  # noqa: PLW0603
    if _raw_store is None:
        raw_store = RawSpanStore(_config_module.WWT_DATA_DIR / "raw" / "spans.db")
        raw_store.initialize()
        _raw_store = raw_store
    return _raw_store


@contextmanager
def _write_lock():
    """쓰기 작업 시 배타 락 획득 — 완료 후 즉시 해제.

    여러 MCP 프로세스가 동시에 ingest해도 순차 처리되어 데이터 유실 없음.
    """
    lock_path = _config_module.WWT_DATA_DIR / "wwt.lock"
    fd = open(lock_path, "w")  # noqa: SIM115
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # 블로킹 — 다른 writer 완료까지 대기
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def _reset_engine() -> None:
    """테스트용 싱글톤 리셋."""
    global _engine, _raw_store  # noqa: PLW0603
    _engine = None
    _raw_store = None


def _append_chunk_preview(
    lines: list[str],
    chunk,
    *,
    max_preview_lines: int,
) -> None:
    has_more = "has_more" if chunk.has_more else "complete"
    lines.append(
        "   "
        f"[chunk:{chunk.id} | span:{chunk.span_id} | {chunk.granularity} | "
        f"turns {chunk.start_turn_index}-{chunk.end_turn_index} | {has_more}]",
    )
    for line in chunk.raw_preview.strip().split("\n")[:max_preview_lines]:
        lines.append(f"   {line[:120]}")
    if chunk.code_count:
        ids = ", ".join(chunk.snippet_ids[:5])
        languages = ", ".join(chunk.code_languages)
        lines.append(
            f"   code: {chunk.code_count} snippets ({languages}) | ids: {ids}",
        )


@mcp.tool()
def search_memory(
    query: str,
    project: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
    git_branch: str | None = None,
    date: str | None = None,
) -> str:
    """과거 대화를 프로젝트/플랫폼/브랜치 기준으로 검색합니다 (기본 회수 도구).

    아래 회수성 트리거가 오면 git log/Bash/Read 전에 이 도구를 먼저 호출하세요.

    트리거 예시:
    - 세션 시작 직후 맥락 파악 — "어제 이 프로젝트 어디까지 했지?",
      "지금 상황 파악해줘", "이어서 작업하자", "맥락 파악해"
      → query='recent technical decisions and architecture choices'
    - 모호한 과거 회수 — "그때 그거 뭐였지?", "이전에 어떻게 했지?",
      "지난번에 뭐라고 했지?"
    - 크로스 에이전트 — "codex/claude/gemini에서 작업한거 파악해",
      "어제 Codex로 한 작업 보여줘" → source 파라미터 지정
    - 크로스 브랜치 — "feature/auth 브랜치에서 했던 작업" → git_branch 지정
    - 특정 날짜 — "어제 뭐 했지?", "2026-04-11에 작업한 것" → date='YYYY-MM-DD'

    결과 preview로 답이 부족하면 반환된 chunk_id로 recall_chunk를 호출하여
    원문을 확장하세요 (2-hop 패턴: search → recall).

    Args:
        query: 검색할 내용 (예: "DB 뭘로 했지?", "Redis 캐시 설정").
            사용자의 자연어 질문에서 핵심 키워드를 그대로 전달해도 충분합니다.
        project: 특정 프로젝트명으로 필터링 (예: "whatwasthat", "frontend").
            미지정 시 cwd에서 basename을 자동 추출합니다.
        cwd: 현재 작업 디렉토리 — project 미지정 시 프로젝트명 자동 감지용.
            agent가 자기 작업 디렉토리를 전달하세요.
        source: 플랫폼 필터 — "claude-code" (Claude Code),
            "gemini-cli" (Gemini CLI), "codex-cli" (Codex CLI).
            크로스 에이전트 회수 시 반드시 지정하세요.
        git_branch: 특정 Git 브랜치로 필터링 (예: "main", "feature/auth").
        date: 날짜 필터 "YYYY-MM-DD" 포맷 (Asia/Seoul 기준).
            해당 날짜에 시작된 세션만 반환합니다.
    """
    engine = _get_engine()

    # 프로젝트 필터 결정: 명시적 project > cwd에서 추출 > 전체 검색
    # 단, source나 git_branch가 명시되면 크로스 프로젝트 검색 의도이므로 cwd 자동 필터 생략
    filter_project = project
    if not filter_project and cwd and not source and not git_branch:
        filter_project = cwd.rstrip("/").split("/")[-1]

    # Self-ROUTE 자동 라우팅: 1차 결과 점수에 따라 확장 여부 결정
    results = engine.search_with_routing(
        query, project=filter_project, source=source, git_branch=git_branch,
        date=date,
    )

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
            _append_chunk_preview(lines, chunk, max_preview_lines=3)
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_all(query: str, date: str | None = None) -> str:
    """모든 프로젝트/모든 플랫폼에 걸쳐 통합 검색합니다 (크로스 프로젝트 회수용).

    사용자가 프로젝트/플랫폼/브랜치를 특정하지 않고, 다른 레포에서 풀었던
    비슷한 문제를 떠올리려 할 때 이 도구를 사용하세요.

    트리거 예시:
    - "다른 프로젝트에서 비슷한 문제 어떻게 풀었지?"
    - "이 mTLS cert chain 이슈 예전에 본 적 있는데"
    - "이 패턴 어느 레포에서 썼더라"

    현재 프로젝트 안에서만 찾고 싶으면 search_memory를 쓰세요.
    의사결정 이유가 필요하면 search_decision을 쓰세요.

    Args:
        query: 검색할 내용 (예: "전에 했던 Redis 설정", "비슷한 버그 해결").
        date: 날짜 필터 "YYYY-MM-DD" 포맷 (Asia/Seoul 기준).
            해당 날짜에 시작된 세션만 반환합니다.
    """
    engine = _get_engine()
    results = engine.search(query, project=None, date=date)

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
            _append_chunk_preview(lines, chunk, max_preview_lines=2)
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_decision(
    query: str,
    project: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
    git_branch: str | None = None,
    date: str | None = None,
) -> str:
    """의사결정 맥락을 검색합니다 — '왜 A 대신 B를 선택했지?' 류 질문 전용.

    내부적으로 "대신/선택/결정/이유/비교/때문에 / instead of / because / chose"
    패턴이 포함된 청크에 점수 가중치를 부여하여 일반 search_memory보다
    "왜"를 담은 chunk를 우선 노출합니다.

    트리거 예시:
    - "왜 Redis를 골랐지?", "왜 Kafka 대신 NATS로 갔지?"
    - "이유가 뭐였지?", "그 트레이드오프 기록 남아있나?"
    - "장단점 비교한 대화 찾아줘"

    '그때 그거 뭐였지?' 같은 일반 회수는 search_memory를 쓰세요.
    이 도구는 의사결정 컨텍스트가 명확할 때만 효과적입니다.

    Args:
        query: 의사결정 검색 쿼리 (예: "왜 Redis를 선택했지?", "DB를 바꾼 이유").
        project: 특정 프로젝트명으로 필터링. 미지정 시 cwd에서 자동 추출.
        cwd: 현재 작업 디렉토리 — project 미지정 시 프로젝트명 자동 감지용.
        source: 플랫폼 필터 — "claude-code", "gemini-cli", "codex-cli".
        git_branch: 특정 Git 브랜치로 필터링.
        date: 날짜 필터 "YYYY-MM-DD" 포맷 (Asia/Seoul 기준).
    """
    engine = _get_engine()

    filter_project = project
    if not filter_project and cwd and not source and not git_branch:
        filter_project = cwd.rstrip("/").split("/")[-1]

    results = engine.search(
        query, project=filter_project, source=source, git_branch=git_branch,
        mode="decision", date=date,
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
            _append_chunk_preview(lines, chunk, max_preview_lines=3)
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def recall_chunk(chunk_id: str, include_neighbors: int = 0) -> str:
    """chunk_id로 full 원문과 full code snippets를 조회합니다 (search의 2-hop 확장).

    search_memory / search_all / search_decision 결과 preview는 청크당
    수 줄만 보여주므로, 정확한 인용·코드·타임스탬프가 필요하면 이 도구로
    원문을 확장하세요. preview에서 끊기는 문장이 결정적 내용을 담고 있을 때,
    또는 해당 세션의 바로 앞뒤 맥락이 필요할 때가 전형적인 사용 시점입니다.

    전형적 흐름:
        1) search_memory(query=...) 호출
        2) 결과 중 관련성 높은 chunk_id 선택
        3) recall_chunk(chunk_id=...) 또는
           recall_chunk(chunk_id=..., include_neighbors=1)

    Args:
        chunk_id: search 결과에 표시된 chunk ID (sha256 앞 16자).
        include_neighbors: 같은 세션에서 앞뒤 span을 몇 개까지 함께 반환할지
            (기본 0 = 해당 span만). 회의 흐름·디버깅 전후 맥락이 필요하면
            1~2로 올려 잡으세요.
    """
    engine = _get_engine()
    raw_store = _get_raw_store()
    collection = engine._vector._get_collection()
    data = collection.get(ids=[chunk_id], include=["metadatas"])
    if not data.get("ids"):
        return f"chunk_id를 찾지 못했습니다: {chunk_id}"

    meta = data["metadatas"][0] if data.get("metadatas") else {}
    span_id = meta.get("span_id", "")
    if not span_id:
        return (
            f"chunk_id={chunk_id}는 v1.0.12 RawSpan metadata가 없습니다. "
            "wwt reset && wwt setup으로 재적재가 필요합니다."
        )

    span = raw_store.get_span(span_id)
    if span is None:
        preview = meta.get("raw_preview", "")
        return (
            f"RawSpan을 찾지 못했습니다: {span_id}\n"
            "재적재가 필요할 수 있습니다.\n\n"
            f"{preview}"
        )

    warning = ""
    with _write_lock():
        raw_store.increment_access_count(span_id)
        try:
            engine._vector.increment_access_counts([chunk_id])
        except Exception as exc:  # cache update failure is non-fatal
            warning = f"\n\n[warning] ChromaDB access_count 동기화 실패: {exc}"

    include_neighbors = max(0, include_neighbors)
    spans = raw_store.get_neighbor_spans(span, include_neighbors)

    lines: list[str] = []
    lines.append(f"chunk: {chunk_id}")
    lines.append(f"span: {span_id}")
    lines.append(f"neighbors: {include_neighbors}")
    lines.append("")

    for current in spans:
        lines.append(
            f"## {current.id} ({current.start_turn_index}-{current.end_turn_index})",
        )
        lines.append(current.raw_text)
        if current.code_snippets:
            lines.append("")
            lines.append("### code_snippets")
            for snippet in current.code_snippets:
                lines.append(f"```{snippet.language} id={snippet.id}")
                lines.append(snippet.code)
                lines.append("```")
        lines.append("")

    if warning:
        lines.append(warning.strip())
    return "\n".join(lines).rstrip()


@mcp.tool()
def ingest_session(path: str) -> str:
    """JSONL 대화 로그를 벡터 DB에 적재합니다.

    Args:
        path: JSONL 파일 또는 디렉토리 경로
    """
    from pathlib import Path

    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import detect_parser

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

    engine = _get_engine()
    raw_store = _get_raw_store()
    total_chunks = 0
    total_spans = 0
    total_embedded = 0

    with _write_lock():
        for session_id, turns in sessions.items():
            if not turns:
                continue
            meta = meta_map.get(session_id)
            spans, chunks = chunk_turns(turns, session_id=session_id, meta=meta)
            if chunks:
                raw_store.upsert_spans(spans)
                embedded = engine._vector.upsert_session_chunks(
                    session_id, chunks, rebuild_bm25=False,
                )
                total_spans += len(spans)
                total_chunks += len(chunks)
                total_embedded += embedded
        engine._vector.rebuild_index()

    return (
        f"완료: {len(sessions)} 세션, {total_spans} spans, "
        f"{total_chunks} 청크 ({total_embedded} 신규 임베딩)"
    )


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
