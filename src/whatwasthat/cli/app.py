"""wwt CLI 앱 - typer 기반 명령어 인터페이스."""

from pathlib import Path

import typer

from whatwasthat.config import WwtConfig

app = typer.Typer(
    name="wwt",
    help="whatwasthat - AI 대화 기억 솔루션",
)


def _get_config() -> WwtConfig:
    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


@app.command()
def init() -> None:
    """WWT 초기 설정 (DB 디렉토리 생성)."""
    config = _get_config()
    from whatwasthat.storage.graph import GraphStore
    from whatwasthat.storage.vector import VectorStore

    graph = GraphStore(config.kuzu_path)
    graph.initialize()
    vector = VectorStore(config.chroma_path)
    vector.initialize()
    typer.echo(f"WWT 초기화 완료: {config.home_dir}")


@app.command()
def ingest(path: str = typer.Argument(help="JSONL 파일 또는 디렉토리 경로")) -> None:
    """대화 로그를 Knowledge Graph로 적재."""
    config = _get_config()
    file_path = Path(path).expanduser()

    from whatwasthat.pipeline.parser import parse_jsonl, parse_session_dir
    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.resolver import resolve_references
    from whatwasthat.pipeline.extractor import extract_triples
    from whatwasthat.storage.graph import GraphStore
    from whatwasthat.storage.vector import VectorStore
    from whatwasthat.models import Entity

    graph = GraphStore(config.kuzu_path)
    graph.initialize()
    vector = VectorStore(config.chroma_path)
    vector.initialize()

    # 파싱
    if file_path.is_dir():
        sessions = parse_session_dir(file_path)
    else:
        session_id = file_path.stem
        sessions = {session_id: parse_jsonl(file_path)}

    total_triples = 0
    for session_id, turns in sessions.items():
        if not turns:
            continue
        typer.echo(f"세션 {session_id}: {len(turns)} 턴 처리 중...")

        # 청킹
        chunks = chunk_turns(turns, session_id=session_id)

        for chunk in chunks:
            # 대명사 해소
            resolved = resolve_references(chunk)
            # 트리플 추출
            triples = extract_triples(resolved)
            if not triples:
                continue
            # 그래프 저장
            graph.add_triples(session_id, triples)
            # 벡터 저장 (엔티티)
            entities: list[Entity] = []
            seen: set[str] = set()
            for t in triples:
                for name, etype in [(t.subject, t.subject_type), (t.object, t.object_type)]:
                    if name not in seen:
                        seen.add(name)
                        entities.append(Entity(
                            id=f"{name[:8].lower().replace(' ', '_')}",
                            name=name, type=etype,
                        ))
            vector.upsert_entities(entities)
            total_triples += len(triples)

    typer.echo(f"완료: {len(sessions)} 세션, {total_triples} 트리플 추출")


@app.command()
def search(query: str = typer.Argument(help="검색 쿼리")) -> None:
    """과거 대화에서 관련 기억 검색."""
    config = _get_config()

    from whatwasthat.storage.graph import GraphStore
    from whatwasthat.storage.vector import VectorStore
    from whatwasthat.search.engine import SearchEngine

    graph = GraphStore(config.kuzu_path)
    graph.initialize()
    vector = VectorStore(config.chroma_path)
    vector.initialize()

    engine = SearchEngine(graph=graph, vector=vector)
    results = engine.search(query)

    if not results:
        typer.echo("관련 기억을 찾지 못했습니다.")
        return

    typer.echo(f"{len(results)}개 세션에서 관련 기억을 찾았습니다:\n")
    for i, result in enumerate(results, 1):
        typer.echo(f"  {i}. 세션 {result.session_id} (점수: {result.score:.2f})")
        for triple in result.triples[:5]:
            temporal_tag = f" [{triple.temporal}]" if triple.temporal else ""
            typer.echo(f"     {triple.subject} —[{triple.predicate}]→ {triple.object}{temporal_tag}")
        typer.echo()


@app.command()
def watch() -> None:
    """백그라운드 데몬 - 새 대화 자동 감지 및 추출. (Phase 2)"""
    typer.echo("watch 기능은 Phase 2에서 구현 예정입니다.")
