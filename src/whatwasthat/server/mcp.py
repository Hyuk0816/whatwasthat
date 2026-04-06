"""WWT MCP 서버 — Claude Code/Desktop에서 대화 기억 검색."""

from mcp.server.fastmcp import FastMCP

from whatwasthat.config import WwtConfig
from whatwasthat.search.engine import SearchEngine
from whatwasthat.storage.vector import VectorStore

mcp = FastMCP(
    "whatwasthat",
    instructions=(
        "사용자가 과거 대화, 이전 작업, 다른 프로젝트 경험을 언급할 때 이 도구를 사용하세요. "
        "예: '그때 그거 뭐였지?', '이전에 어떻게 했지?', '다른 프로젝트에서 쓴 방법', "
        "'전에 Redis 설정 어떻게 했었지?', '지난번에 비슷한 버그 어떻게 고쳤지?' 등. "
        "search_memory는 현재 프로젝트 맥락으로 검색하고, "
        "search_all은 모든 프로젝트에서 검색합니다."
    ),
)


def _get_engine() -> SearchEngine:
    """SearchEngine 싱글톤."""
    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    vector = VectorStore(config.chroma_path)
    vector.initialize()
    return SearchEngine(vector=vector)


@mcp.tool()
def search_memory(
    query: str,
    project: str | None = None,
    cwd: str | None = None,
) -> str:
    """과거 대화에서 관련 기억을 검색합니다.

    Args:
        query: 검색할 내용 (예: "DB 뭘로 했지?", "Redis 캐시 설정")
        project: 특정 프로젝트로 필터링 (예: "whatwasthat")
        cwd: 현재 작업 디렉토리 (자동 감지용, 프로젝트명 추출에 사용)
    """
    engine = _get_engine()

    # 프로젝트 필터 결정: 명시적 project > cwd에서 추출 > 전체 검색
    filter_project = project
    if not filter_project and cwd:
        filter_project = cwd.rstrip("/").split("/")[-1]

    results = engine.search(query, project=filter_project)

    if not results:
        return "관련 기억을 찾지 못했습니다."

    lines: list[str] = []
    lines.append(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")

    for i, result in enumerate(results, 1):
        branch = f" ({result.git_branch})" if result.git_branch else ""
        lines.append(f"{i}. {result.project}{branch} (점수: {result.score:.2f})")
        for chunk in result.chunks[:3]:
            for line in chunk.raw_text.strip().split("\n")[:3]:
                lines.append(f"   {line[:120]}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_all(query: str) -> str:
    """모든 프로젝트에서 대화 기억을 검색합니다.

    Args:
        query: 검색할 내용
    """
    engine = _get_engine()
    results = engine.search(query, project=None)

    if not results:
        return "관련 기억을 찾지 못했습니다."

    lines: list[str] = []
    lines.append(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")

    for i, result in enumerate(results, 1):
        branch = f" ({result.git_branch})" if result.git_branch else ""
        lines.append(f"{i}. {result.project}{branch} (점수: {result.score:.2f})")
        for chunk in result.chunks[:2]:
            for line in chunk.raw_text.strip().split("\n")[:2]:
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
    from whatwasthat.pipeline.parser import parse_jsonl, parse_session_dir, parse_session_meta

    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    vector = VectorStore(config.chroma_path)
    vector.initialize()

    file_path = Path(path).expanduser()
    if file_path.is_dir():
        sessions = parse_session_dir(file_path)
        meta_map = {f.stem: parse_session_meta(f) for f in sorted(file_path.glob("*.jsonl"))}
    else:
        sid = file_path.stem
        sessions = {sid: parse_jsonl(file_path)}
        meta_map = {sid: parse_session_meta(file_path)}

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

    return f"완료: {len(sessions)} 세션, {total_chunks} 청크 ({total_embedded} 신규 임베딩)"
