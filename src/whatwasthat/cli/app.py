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
def setup() -> None:
    """WWT 전체 설정 — DB 초기화 + Stop Hook + MCP 서버 등록."""
    import json
    import shutil
    import subprocess

    config = _get_config()

    # 1. DB 초기화
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()
    typer.echo("✓ DB 초기화 완료")

    # 2. Stop Hook 스크립트 설치
    hooks_dir = Path.home() / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_script = hooks_dir / "wwt_auto_ingest.sh"

    uv_path = shutil.which("uv") or "uv"

    hook_content = f"""#!/bin/bash
INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi
{uv_path} run --directory {Path(__file__).resolve().parents[3]} wwt ingest "$TRANSCRIPT_PATH" \
    >> "$HOME/.wwt/ingest.log" 2>&1 &
exit 0
"""
    hook_script.write_text(hook_content)
    hook_script.chmod(0o755)
    typer.echo("✓ Stop Hook 스크립트 설치 완료")

    # 3. settings.json에 Stop Hook 등록
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    hook_cmd = f"bash {hook_script}"
    already_registered = any(
        hook_cmd in h.get("command", "")
        for entry in stop_hooks
        for h in entry.get("hooks", [])
    )

    if not already_registered:
        stop_hooks.append({
            "hooks": [{
                "type": "command",
                "command": hook_cmd,
                "timeout": 15,
                "async": True,
            }]
        })
        settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        typer.echo("✓ Stop Hook 등록 완료 (settings.json)")
    else:
        typer.echo("✓ Stop Hook 이미 등록됨")

    # 4. MCP 서버 글로벌 등록
    try:
        result = subprocess.run(
            ["claude", "mcp", "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        mcp_exists = "whatwasthat" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        mcp_exists = False

    if not mcp_exists:
        try:
            project_dir = str(Path(__file__).resolve().parents[3])
            subprocess.run(
                ["claude", "mcp", "add", "whatwasthat", "--scope", "user",
                 "--", uv_path, "--directory", project_dir, "run", "wwt-mcp"],
                timeout=10,
            )
            typer.echo("✓ MCP 서버 글로벌 등록 완료")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            typer.echo("⚠ MCP 등록 실패 — 수동으로 실행: claude mcp add whatwasthat --scope user")
    else:
        typer.echo("✓ MCP 서버 이미 등록됨")

    typer.echo("\n설정 완료! Claude Code를 재시작하세요.")


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
