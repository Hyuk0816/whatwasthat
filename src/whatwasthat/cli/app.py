"""wwt CLI 앱 - typer 기반 명령어 인터페이스."""

from pathlib import Path

import typer

from whatwasthat.config import WwtConfig

app = typer.Typer(
    name="wwt",
    help="whatwasthat - AI 대화 기억 검색",
)


def _get_config() -> WwtConfig:
    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


@app.command()
def init() -> None:
    """WWT 초기 설정 (DB 디렉토리 생성)."""
    config = _get_config()
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()
    typer.echo(f"WWT 초기화 완료: {config.home_dir}")


@app.command()
def ingest(path: str = typer.Argument(help="JSONL 파일 또는 디렉토리 경로")) -> None:
    """대화 로그를 벡터 DB로 적재."""
    config = _get_config()
    file_path = Path(path).expanduser()

    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import parse_jsonl, parse_session_dir, parse_session_meta
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()

    if file_path.is_dir():
        sessions = parse_session_dir(file_path)
        meta_map = {
            f.stem: parse_session_meta(f)
            for f in sorted(file_path.glob("*.jsonl"))
        }
    else:
        session_id = file_path.stem
        sessions = {session_id: parse_jsonl(file_path)}
        meta_map = {session_id: parse_session_meta(file_path)}

    total_chunks = 0
    for si, (session_id, turns) in enumerate(sessions.items(), 1):
        if not turns:
            continue
        meta = meta_map.get(session_id)
        project_label = meta.project if meta else session_id[:12]
        typer.echo(f"\n[{si}/{len(sessions)}] {project_label} ({len(turns)} 턴)")

        chunks = chunk_turns(turns, session_id=session_id, meta=meta)
        if not chunks:
            typer.echo("  → 유효한 청크 없음 (스킵)")
            continue
        typer.echo(f"  → {len(chunks)}개 청크 벡터화")
        vector.upsert_chunks(chunks)
        total_chunks += len(chunks)

    typer.echo(f"\n완료: {len(sessions)} 세션, {total_chunks} 청크 저장")


@app.command()
def search(
    query: str = typer.Argument(help="검색 쿼리"),
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 필터"),
    all_projects: bool = typer.Option(False, "--all", "-a", help="전체 프로젝트 검색"),
) -> None:
    """과거 대화에서 관련 기억 검색."""
    config = _get_config()

    from whatwasthat.search.engine import SearchEngine
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()

    engine = SearchEngine(vector=vector)
    filter_project = None if all_projects else project
    results = engine.search(query, project=filter_project)

    if not results:
        typer.echo("관련 기억을 찾지 못했습니다.")
        return

    typer.echo(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")
    for i, result in enumerate(results, 1):
        branch_tag = f" ({result.git_branch})" if result.git_branch else ""
        header = f"  {i}. {result.project}{branch_tag} (점수: {result.score:.2f})"
        typer.echo(header)
        for chunk in result.chunks[:3]:
            lines = chunk.raw_text.strip().split("\n")[:2]
            for line in lines:
                typer.echo(f"     {line[:100]}")
        typer.echo()


@app.command()
def watch() -> None:
    """백그라운드 데몬 - 새 대화 자동 감지. (Phase 2)"""
    typer.echo("watch 기능은 Phase 2에서 구현 예정입니다.")
