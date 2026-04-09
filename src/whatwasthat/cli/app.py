"""wwt CLI 앱 - typer 기반 명령어 인터페이스."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import typer

from whatwasthat.config import WwtConfig

if TYPE_CHECKING:
    from whatwasthat.storage.vector import VectorStore

app = typer.Typer(
    name="wwt",
    help="whatwasthat - AI 대화 기억 검색",
)


def _get_config() -> WwtConfig:
    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


class _IngestStats(TypedDict):
    sessions: int
    chunks: int
    embedded: int
    elapsed_ms: int


def _bulk_ingest_directory(
    vector: VectorStore,
    directory: Path,
    patterns: list[str],
    label: str,
    *,
    rebuild_at_end: bool = True,
) -> _IngestStats:
    """Shared bulk-ingest helper used by both `setup` and `ingest` commands.

    Reads every file under `directory` matching any of the `patterns`, parses
    sessions, chunks them, and performs a SINGLE `vector.upsert_chunks(...)`
    call with `rebuild_bm25=False` so the ONNX embedding pipeline batches all
    documents at once. BM25 rebuild is deferred to the end (if requested) so
    large ingests stay cheap.

    Args:
        vector: initialized VectorStore
        directory: directory to scan (may be missing — silently noop)
        patterns: list of glob patterns (e.g. ["**/*.jsonl"])
        label: human-readable platform name for progress messages
        rebuild_at_end: if True, call vector.rebuild_index() after upsert

    Returns:
        Stats dict: sessions / chunks / embedded / elapsed_ms
    """
    # Late imports to avoid circular dependencies and keep cold-import cheap.
    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import detect_parser

    start = time.monotonic()
    stats: _IngestStats = {
        "sessions": 0, "chunks": 0, "embedded": 0, "elapsed_ms": 0,
    }

    if not directory.is_dir():
        stats["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        return stats

    files: list[Path] = []
    for pattern in patterns:
        files.extend(directory.glob(pattern))
    files = sorted({f for f in files if f.is_file()})

    if not files:
        typer.echo(
            f"ℹ [{label}] no existing sessions — will ingest on next turn",
        )
        stats["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        return stats

    total = len(files)
    typer.echo(f"\n[{label}] ingesting {total} sessions...")

    all_chunks: list = []
    session_count = 0
    parse_start = time.monotonic()

    for i, f in enumerate(files, 1):
        parser = detect_parser(f)
        if parser is None:
            continue
        turns = parser.parse_turns(f)
        if not turns:
            continue
        meta = parser.parse_meta(f)
        chunks = chunk_turns(turns, session_id=f.stem, meta=meta)
        if not chunks:
            continue
        all_chunks.extend(chunks)
        session_count += 1

        # Progress at every ~10% or at the last file
        if i == total or i % max(1, total // 10) == 0:
            pct = i * 100 // total
            typer.echo(
                f"  [{label}] parse {pct}% ({i}/{total}) — "
                f"{session_count} sessions, {len(all_chunks)} chunks",
            )

    parse_ms = int((time.monotonic() - parse_start) * 1000)

    if not all_chunks:
        stats["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        typer.echo(f"✓ [{label}] no chunks to ingest ({parse_ms} ms)")
        return stats

    # Single bulk upsert → ONNX batching efficiency
    embed_start = time.monotonic()
    typer.echo(f"  [{label}] embedding {len(all_chunks)} chunks in bulk...")
    vector.upsert_chunks(all_chunks, rebuild_bm25=False)
    embed_ms = int((time.monotonic() - embed_start) * 1000)

    if rebuild_at_end:
        rebuild_start = time.monotonic()
        vector.rebuild_index()
        rebuild_ms = int((time.monotonic() - rebuild_start) * 1000)
    else:
        rebuild_ms = 0

    total_ms = int((time.monotonic() - start) * 1000)
    stats["sessions"] = session_count
    stats["chunks"] = len(all_chunks)
    stats["embedded"] = len(all_chunks)  # bulk path: every chunk is freshly embedded
    stats["elapsed_ms"] = total_ms

    suffix = f" · bm25 {rebuild_ms} ms" if rebuild_at_end else ""
    typer.echo(
        f"✓ [{label}] done: {session_count} sessions, {len(all_chunks)} chunks "
        f"— parse {parse_ms} ms · embed {embed_ms} ms{suffix} · total {total_ms} ms",
    )
    return stats


@app.command()
def init() -> None:
    """WWT 초기 설정 (DB 디렉토리 생성)."""
    config = _get_config()
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()
    typer.echo(f"WWT 초기화 완료: {config.home_dir}")


def _install_codex_hook(hooks_dir: Path) -> Path:
    """Codex CLI Stop hook 스크립트 생성.

    Codex Stop payload:
      session_id, transcript_path, cwd, hook_event_name, model, turn_id,
      stop_hook_active, last_assistant_message
    """
    import shutil
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script = hooks_dir / "codex_ingest.sh"
    wwt_path = shutil.which("wwt") or "wwt"
    script.write_text(f"""#!/bin/bash
INPUT=$(cat)
LOG="$HOME/.wwt/ingest.log"
TS=$(date +%Y-%m-%dT%H:%M:%S%z)

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
TURN_ID=$(echo "$INPUT" | jq -r '.turn_id // empty')
PROJECT=$(basename "$CWD")

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "$TS source=codex-cli project=$PROJECT" \
         "session=$SESSION_ID status=skip_no_transcript" >> "$LOG"
    exit 0
fi

(
  echo "$TS source=codex-cli project=$PROJECT" \
       "session=$SESSION_ID turn=$TURN_ID" \
       "transcript=$TRANSCRIPT_PATH status=ingest_start"
  {wwt_path} ingest "$TRANSCRIPT_PATH" 2>&1
  TS_DONE=$(date +%Y-%m-%dT%H:%M:%S%z)
  echo "$TS_DONE source=codex-cli project=$PROJECT" \
       "session=$SESSION_ID status=ingest_done"
) >> "$LOG" &
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

    # 0. HuggingFace 경고 suppress
    import os
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

    # 1. DB 초기화
    typer.echo("DB 초기화 중... (최초 실행 시 임베딩 모델 ~470MB 다운로드)")
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
                typer.echo(
                    "⚠ Gemini MCP 등록 실패 — 수동: gemini mcp add whatwasthat wwt-mcp --scope user"
                )
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

    # 5. 기존 세션 자동 적재 (순차, 플랫폼별 진행 표시)
    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import detect_parser

    def _ingest_platform(
        label: str, directory: Path, patterns: list[str],
    ) -> None:
        """플랫폼별 기존 세션을 순차 적재 (진행 표시 포함)."""
        if not directory.is_dir():
            return

        files: list[Path] = []
        for pattern in patterns:
            files.extend(directory.glob(pattern))
        files = sorted(set(f for f in files if f.is_file()))

        if not files:
            typer.echo(f"ℹ {label} 대화 기록 없음 — 새 대화 후 자동 적재됩니다")
            return

        typer.echo(f"\n[{label}] {len(files)}개 세션 적재 중...")
        total = len(files)
        session_count = 0
        total_chunks = 0
        total_embedded = 0

        for i, f in enumerate(files, 1):
            parser = detect_parser(f)
            if parser is None:
                continue
            turns = parser.parse_turns(f)
            if not turns:
                continue
            meta = parser.parse_meta(f)
            chunks = chunk_turns(turns, session_id=f.stem, meta=meta)
            if not chunks:
                continue
            embedded = vector.upsert_session_chunks(
                f.stem, chunks, rebuild_bm25=False,
            )
            session_count += 1
            total_chunks += len(chunks)
            total_embedded += embedded

            # 진행 표시 (10% 단위 + 마지막)
            if i == total or i % max(1, total // 10) == 0:
                pct = i * 100 // total
                typer.echo(
                    f"  [{label}] {pct}% ({i}/{total}) — {session_count} 세션, {total_chunks} 청크"
                )

        if total_chunks:
            vector.rebuild_index()
        msg = (
            f"✓ [{label}] 완료: {session_count} 세션, "
            f"{total_chunks} 청크 ({total_embedded} 신규 임베딩)"
        )
        typer.echo(msg)

    _ingest_platform(
        "Claude Code",
        Path.home() / ".claude" / "projects",
        ["**/*.jsonl"],
    )
    _ingest_platform(
        "Gemini CLI",
        Path.home() / ".gemini" / "tmp",
        ["**/chats/*.json"],
    )
    _ingest_platform(
        "Codex CLI",
        Path.home() / ".codex" / "sessions",
        ["**/*.jsonl"],
    )

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

        # ~/.codex/hooks.json에 자동 등록
        codex_hooks_path = codex_dir / "hooks.json"
        hook_cmd = "bash ~/.wwt/hooks/codex_ingest.sh"
        if codex_hooks_path.exists():
            codex_hooks = json.loads(codex_hooks_path.read_text())
        else:
            codex_hooks = {}

        hooks_cfg = codex_hooks.setdefault("hooks", {})
        stop_hooks_list = hooks_cfg.setdefault("Stop", [])

        already_codex = any(
            hook_cmd in h.get("command", "")
            for entry in stop_hooks_list
            for h in entry.get("hooks", [])
        )
        if not already_codex:
            stop_hooks_list.append({
                "hooks": [{
                    "type": "command",
                    "command": hook_cmd,
                }]
            })
            codex_hooks_path.write_text(
                json.dumps(codex_hooks, indent=2, ensure_ascii=False) + "\n"
            )
            typer.echo("✓ Codex CLI Stop Hook 등록 완료")
        else:
            typer.echo("✓ Codex CLI Hook 이미 등록됨")

    typer.echo("\n설정 완료! 각 플랫폼을 재시작하여 확인하세요.")


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

    # 세션별 파싱 → 청크 수집 → 벌크 upsert (BM25는 마지막에 1회)
    is_bulk = len(sessions) > 1
    total = len(sessions)
    all_chunks: list = []
    session_count = 0
    for si, (session_id, turns) in enumerate(sessions.items(), 1):
        if not turns:
            continue
        meta = meta_map.get(session_id)
        chunks = chunk_turns(turns, session_id=session_id, meta=meta)
        if not chunks:
            continue
        if is_bulk:
            all_chunks.extend(chunks)
            session_count += 1
        else:
            # 단일 세션: 증분 upsert (변경 감지 활용)
            embedded = vector.upsert_session_chunks(
                session_id, chunks, rebuild_bm25=True,
            )
            typer.echo(f"\n완료: 1 세션, {len(chunks)} 청크 ({embedded} 신규 임베딩)")
            return
        if si % 50 == 0 or si == total:
            typer.echo(f"  파싱: {si}/{total} 세션, {len(all_chunks)} 청크")

    if not all_chunks:
        typer.echo("적재할 청크가 없습니다.")
        return

    # 벌크 모드: 전체 청크를 한 번에 upsert → ONNX 배치 효율 극대화
    typer.echo(f"  임베딩: {len(all_chunks)} 청크 일괄 처리 중...")
    vector.upsert_chunks(all_chunks, rebuild_bm25=False)
    vector.rebuild_index()

    typer.echo(f"\n완료: {session_count} 세션, {len(all_chunks)} 청크 (벌크 임베딩)")


@app.command()
def search(
    query: str = typer.Argument(help="검색 쿼리"),
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 필터"),
    all_projects: bool = typer.Option(False, "--all", "-a", help="전체 프로젝트 검색"),
    source: str = typer.Option(
        None, "--source", "-s", help="플랫폼 필터 (claude-code, gemini-cli, codex-cli)",
    ),
    branch: str = typer.Option(None, "--branch", "-b", help="Git 브랜치 필터"),
    mode: str = typer.Option(None, "--mode", "-m", help="검색 모드 (decision, code)"),
) -> None:
    """과거 대화에서 관련 기억 검색."""
    config = _get_config()

    from whatwasthat.search.engine import SearchEngine
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()

    engine = SearchEngine(vector=vector)
    filter_project = None if all_projects else project
    results = engine.search(
        query, project=filter_project, source=source, git_branch=branch, mode=mode,
    )

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
def why(
    query: str = typer.Argument(help="의사결정 검색 쿼리"),
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 필터"),
    all_projects: bool = typer.Option(False, "--all", "-a", help="전체 프로젝트 검색"),
    source: str = typer.Option(None, "--source", "-s", help="플랫폼 필터"),
    branch: str = typer.Option(None, "--branch", "-b", help="Git 브랜치 필터"),
) -> None:
    """의사결정 맥락 검색 — '왜 그렇게 했지?' 에 답합니다."""
    config = _get_config()

    from whatwasthat.search.engine import SearchEngine
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()

    engine = SearchEngine(vector=vector)
    filter_project = None if all_projects else project
    results = engine.search(
        query, project=filter_project, source=source, git_branch=branch, mode="decision",
    )

    if not results:
        typer.echo("관련 의사결정 기억을 찾지 못했습니다.")
        return

    typer.echo(f"{len(results)}개 세션에서 의사결정 기억을 찾았습니다:\n")
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
def reset(
    force: bool = typer.Option(False, "--force", "-f", help="확인 없이 즉시 삭제"),
) -> None:
    """모든 적재 데이터 삭제 (벡터 DB + BM25 캐시 초기화)."""
    import shutil as _shutil

    config = _get_config()
    vector_dir = config.chroma_path
    bm25_dir = config.bm25_index_path.parent

    targets = [p for p in (vector_dir, bm25_dir) if p.exists()]
    if not targets:
        typer.echo("삭제할 데이터가 없습니다.")
        return

    if not force:
        confirm = typer.confirm("모든 적재 데이터를 삭제합니다. 계속할까요?")
        if not confirm:
            typer.echo("취소되었습니다.")
            return

    for target in targets:
        _shutil.rmtree(target)
    typer.echo("✓ 모든 적재 데이터 삭제 완료 (vector + bm25)")
    typer.echo("  다시 적재하려면: wwt setup 또는 wwt ingest <경로>")
