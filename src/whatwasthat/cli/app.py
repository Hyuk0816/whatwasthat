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


def _install_codex_hook(hooks_dir: Path) -> Path:
    """Codex CLI Stop hook 스크립트 생성."""
    import shutil
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script = hooks_dir / "codex_ingest.sh"
    wwt_path = shutil.which("wwt") or "wwt"
    script.write_text(f"""#!/bin/bash
INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi
{wwt_path} ingest "$TRANSCRIPT_PATH" >> "$HOME/.wwt/ingest.log" 2>&1 &
exit 0
""")
    script.chmod(0o755)
    return script


def _install_gemini_hook(hooks_dir: Path) -> Path:
    """Gemini CLI AfterAgent hook 스크립트 생성."""
    import shutil
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script = hooks_dir / "gemini_ingest.sh"
    wwt_path = shutil.which("wwt") or "wwt"
    script.write_text(f"""#!/bin/bash
INPUT=$(cat)
echo '{{"decision": "allow"}}'
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi
{wwt_path} ingest "$TRANSCRIPT_PATH" >> "$HOME/.wwt/ingest.log" 2>&1 &
exit 0
""")
    script.chmod(0o755)
    return script


def _register_gemini_hook(settings_path: Path) -> bool:
    """~/.gemini/settings.json에 AfterAgent hook 등록."""
    import json
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    hooks = settings.setdefault("hooks", {})
    after_hooks = hooks.setdefault("AfterAgent", [])

    hook_cmd = "bash ~/.wwt/hooks/gemini_ingest.sh"
    already = any(
        hook_cmd in h.get("command", "")
        for entry in after_hooks
        for h in entry.get("hooks", [])
    )
    if already:
        return False

    after_hooks.append({
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": hook_cmd,
            "name": "wwt-ingest",
            "timeout": 60000,
        }]
    })
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return True


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

    wwt_path = shutil.which("wwt") or "wwt"

    hook_content = f"""#!/bin/bash
INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi
{wwt_path} ingest "$TRANSCRIPT_PATH" \
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
            wwt_mcp_path = shutil.which("wwt-mcp") or "wwt-mcp"
            subprocess.run(
                ["claude", "mcp", "add", "whatwasthat", "--scope", "user",
                 "--", wwt_mcp_path],
                timeout=10,
            )
            typer.echo("✓ MCP 서버 글로벌 등록 완료")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            typer.echo("⚠ MCP 등록 실패 — 수동으로 실행: claude mcp add whatwasthat --scope user")
    else:
        typer.echo("✓ MCP 서버 이미 등록됨")

    # 4-2. Gemini CLI MCP 등록
    if shutil.which("gemini"):
        try:
            result = subprocess.run(
                ["gemini", "mcp", "list"],
                capture_output=True, text=True, timeout=10,
            )
            gemini_mcp_exists = "whatwasthat" in result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            gemini_mcp_exists = False

        if not gemini_mcp_exists:
            try:
                wwt_mcp_path = shutil.which("wwt-mcp") or "wwt-mcp"
                subprocess.run(
                    ["gemini", "mcp", "add", "whatwasthat", wwt_mcp_path,
                     "--scope", "user"],
                    timeout=10,
                )
                typer.echo("✓ Gemini CLI MCP 서버 등록 완료")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                typer.echo("⚠ Gemini MCP 등록 실패 — 수동: gemini mcp add whatwasthat wwt-mcp --scope user")
        else:
            typer.echo("✓ Gemini CLI MCP 서버 이미 등록됨")

    # 4-3. Codex CLI MCP 등록
    if shutil.which("codex"):
        try:
            result = subprocess.run(
                ["codex", "mcp", "list"],
                capture_output=True, text=True, timeout=10,
            )
            codex_mcp_exists = "whatwasthat" in result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            codex_mcp_exists = False

        if not codex_mcp_exists:
            try:
                wwt_mcp_path = shutil.which("wwt-mcp") or "wwt-mcp"
                subprocess.run(
                    ["codex", "mcp", "add", "whatwasthat",
                     "--", wwt_mcp_path],
                    timeout=10,
                )
                typer.echo("✓ Codex CLI MCP 서버 등록 완료")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                typer.echo("⚠ Codex MCP 등록 실패 — 수동: codex mcp add whatwasthat -- wwt-mcp")
        else:
            typer.echo("✓ Codex CLI MCP 서버 이미 등록됨")

    # 5. 기존 세션 자동 적재
    from subprocess import Popen

    # 5-1. Claude Code
    claude_projects = Path.home() / ".claude" / "projects"
    if claude_projects.is_dir():
        jsonl_files = list(claude_projects.rglob("*.jsonl"))
        if jsonl_files:
            typer.echo(f"\n기존 Claude Code 대화 로그 발견 ({len(jsonl_files)}개). 자동 적재 시작...")
            Popen(
                [shutil.which("wwt") or "wwt", "ingest", str(claude_projects)],
                start_new_session=True,
            )
            typer.echo("✓ Claude Code 백그라운드 적재 시작 (로그: ~/.wwt/ingest.log)")
        else:
            typer.echo("ℹ Claude Code 대화 기록 없음 — 새 대화 후 자동 적재됩니다")

    # 5-2. Gemini CLI
    gemini_tmp = Path.home() / ".gemini" / "tmp"
    if gemini_tmp.is_dir():
        gemini_json_files = list(gemini_tmp.glob("**/chats/*.json"))
        if gemini_json_files:
            typer.echo(f"\n기존 Gemini CLI 대화 로그 발견 ({len(gemini_json_files)}개). 자동 적재 시작...")
            Popen(
                [shutil.which("wwt") or "wwt", "ingest", str(gemini_tmp)],
                start_new_session=True,
            )
            typer.echo("✓ Gemini CLI 백그라운드 적재 시작 (로그: ~/.wwt/ingest.log)")
        else:
            typer.echo("ℹ Gemini CLI 대화 기록 없음 — 새 대화 후 자동 적재됩니다")

    # 5-3. Codex CLI
    codex_sessions = Path.home() / ".codex" / "sessions"
    if codex_sessions.is_dir():
        codex_jsonl_files = list(codex_sessions.rglob("*.jsonl"))
        if codex_jsonl_files:
            typer.echo(f"\n기존 Codex CLI 대화 로그 발견 ({len(codex_jsonl_files)}개). 자동 적재 시작...")
            Popen(
                [shutil.which("wwt") or "wwt", "ingest", str(codex_sessions)],
                start_new_session=True,
            )
            typer.echo("✓ Codex CLI 백그라운드 적재 시작 (로그: ~/.wwt/ingest.log)")
        else:
            typer.echo("ℹ Codex CLI 대화 기록 없음 — 새 대화 후 자동 적재됩니다")

    # 6. Gemini CLI Hook 설치 (Gemini CLI가 설치된 경우)
    gemini_dir = Path.home() / ".gemini"
    if gemini_dir.is_dir():
        wwt_hooks = Path.home() / ".wwt" / "hooks"
        _install_gemini_hook(wwt_hooks)
        gemini_settings = gemini_dir / "settings.json"
        if _register_gemini_hook(gemini_settings):
            typer.echo("✓ Gemini CLI AfterAgent Hook 등록 완료")
        else:
            typer.echo("✓ Gemini CLI Hook 이미 등록됨")

    # 7. Codex CLI Hook 설치 (Codex CLI가 설치된 경우)
    codex_dir = Path.home() / ".codex"
    if codex_dir.is_dir():
        wwt_hooks = Path.home() / ".wwt" / "hooks"
        _install_codex_hook(wwt_hooks)
        typer.echo("✓ Codex CLI Stop Hook 스크립트 생성 완료")
        typer.echo("  수동 등록 필요: Codex 프로젝트의 .codex/hooks.json에 추가")
        typer.echo('  {"hooks":{"Stop":[{"hooks":[{"type":"command","command":"bash ~/.wwt/hooks/codex_ingest.sh"}]}]}}')

    typer.echo("\n설정 완료! Claude Code를 재시작하세요.")


@app.command()
def ingest(path: str = typer.Argument(help="JSONL 파일 또는 디렉토리 경로")) -> None:
    """대화 로그를 벡터 DB로 적재."""
    config = _get_config()
    file_path = Path(path).expanduser()

    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import detect_parser
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()

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
            typer.echo(f"지원하지 않는 파일 형식: {file_path}")
            return
        session_id = file_path.stem
        sessions = {session_id: parser.parse_turns(file_path)}
        meta_map = {session_id: parser.parse_meta(file_path)}

    # 세션별 파싱 → 증분 upsert (대량 적재 시 BM25 재구축 지연)
    is_bulk = len(sessions) > 1
    total = len(sessions)
    total_embedded = 0
    total_chunks = 0
    session_count = 0
    for si, (session_id, turns) in enumerate(sessions.items(), 1):
        if not turns:
            continue
        meta = meta_map.get(session_id)
        chunks = chunk_turns(turns, session_id=session_id, meta=meta)
        if not chunks:
            continue
        embedded = vector.upsert_session_chunks(
            session_id, chunks, rebuild_bm25=not is_bulk,
        )
        total_embedded += embedded
        total_chunks += len(chunks)
        session_count += 1
        if si % 50 == 0 or si == total:
            typer.echo(f"  파싱: {si}/{total} 세션, {total_chunks} 청크")

    if not total_chunks:
        typer.echo("적재할 청크가 없습니다.")
        return

    if is_bulk:
        vector.rebuild_index()

    typer.echo(f"\n완료: {session_count} 세션, {total_chunks} 청크 ({total_embedded} 신규 임베딩)")


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
        source_tag = f" [{result.source}]" if result.source else ""
        header = f"  {i}. {result.project}{branch_tag}{source_tag} (점수: {result.score:.2f})"
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
