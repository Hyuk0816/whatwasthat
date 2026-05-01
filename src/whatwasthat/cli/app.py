"""wwt CLI 앱 - typer 기반 명령어 인터페이스."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import typer

from whatwasthat.config import WwtConfig

if TYPE_CHECKING:
    from whatwasthat.storage.raw_store import RawSpanStore
    from whatwasthat.storage.vector import VectorStore

app = typer.Typer(
    name="wwt",
    help="whatwasthat - AI 대화 기억 검색",
)


def _get_config() -> WwtConfig:
    config = WwtConfig()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def _raw_spans_path(config) -> Path:
    """Resolve raw span DB path, including lightweight test config stubs."""
    if hasattr(config, "raw_spans_path"):
        return config.raw_spans_path
    if hasattr(config, "chroma_path"):
        return Path(config.chroma_path).parent / "raw" / "spans.db"
    return Path.home() / ".wwt" / "data" / "raw" / "spans.db"


def _current_project_name() -> str:
    """현재 작업 디렉토리 기준 프로젝트명."""
    return Path.cwd().name


def _remote_summary_counts(summary) -> tuple[int, int]:
    """dict/model 모두 허용하는 요약 추출."""
    if isinstance(summary, dict):
        return int(summary.get("uploaded", 0)), int(summary.get("failed", 0))
    return int(getattr(summary, "uploaded", 0)), int(getattr(summary, "failed", 0))


def _run_remote_ingest_for_date(
    *,
    env: str,
    date: str,
    source: str | None,
    project: str | None,
) -> None:
    """날짜 범위 세션 discovery 후 원격 게이트웨이에 업로드."""
    from whatwasthat.remote.client import RemoteGatewayClient
    from whatwasthat.remote.config import RemoteGatewayConfig
    from whatwasthat.remote.discovery import collect_sessions_for_date

    sessions = collect_sessions_for_date(
        env=env,
        date=date,
        source=source,
        project=project,
    )
    if not sessions:
        typer.echo("업로드할 세션이 없습니다.")
        return

    client = RemoteGatewayClient(RemoteGatewayConfig.from_env())
    summary = client.upload_sessions(sessions)
    uploaded, failed = _remote_summary_counts(summary)
    typer.echo(f"원격 업로드 완료: {uploaded} 성공, {failed} 실패")


def _run_remote_ingest_all(*, env: str, source: str) -> None:
    """특정 source 전체 세션을 원격 게이트웨이에 업로드."""
    from whatwasthat.remote.client import RemoteGatewayClient
    from whatwasthat.remote.config import RemoteGatewayConfig
    from whatwasthat.remote.discovery import collect_all_sessions_for_source

    sessions = collect_all_sessions_for_source(env=env, source=source)
    if not sessions:
        typer.echo("업로드할 세션이 없습니다.")
        return

    client = RemoteGatewayClient(RemoteGatewayConfig.from_env())
    summary = client.upload_sessions(sessions)
    uploaded, failed = _remote_summary_counts(summary)
    typer.echo(f"원격 업로드 완료: {uploaded} 성공, {failed} 실패")


class _IngestStats(TypedDict):
    sessions: int
    chunks: int
    embedded: int
    elapsed_ms: int


# ONNX 임베딩 배치 크기 — 메모리 피크 제한 (v1.0.11.1)
# 1694 청크를 한 번에 upsert하면 ChromaDB가 단일 ONNX forward로 처리해 GB 단위
# 메모리를 요구함. 64 배치로 쪼개면 피크 ~100MB로 떨어져 스와핑을 방지한다.
_BULK_EMBED_BATCH_SIZE = 64


def _bulk_ingest_directory(
    vector: VectorStore,
    directory: Path,
    patterns: list[str],
    label: str,
    *,
    raw_store: RawSpanStore | None = None,
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
        raw_store: initialized RawSpanStore. If omitted, one is created from config.
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
    from whatwasthat.storage.raw_store import RawSpanStore

    if raw_store is None:
        raw_store = RawSpanStore(_raw_spans_path(_get_config()))
        raw_store.initialize()

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

    all_spans: list = []
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
        spans, chunks = chunk_turns(turns, session_id=f.stem, meta=meta)
        if not chunks:
            continue
        all_spans.extend(spans)
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

    # Batched upsert — ONNX 임베딩 메모리 피크 제한
    # _BULK_EMBED_BATCH_SIZE 단위로 쪼개 upsert해 메모리 피크를 선형에서 상수로 낮춘다.
    embed_start = time.monotonic()
    total_chunks = len(all_chunks)
    raw_store.upsert_spans(all_spans)
    typer.echo(
        f"  [{label}] embedding {total_chunks} chunks "
        f"(batch={_BULK_EMBED_BATCH_SIZE})...",
    )
    next_report = max(1, total_chunks // 10)
    for i in range(0, total_chunks, _BULK_EMBED_BATCH_SIZE):
        batch = all_chunks[i : i + _BULK_EMBED_BATCH_SIZE]
        vector.upsert_chunks(batch, rebuild_bm25=False)
        done = min(i + _BULK_EMBED_BATCH_SIZE, total_chunks)
        if done >= next_report or done == total_chunks:
            pct = done * 100 // total_chunks
            typer.echo(
                f"  [{label}] embedded {pct}% ({done}/{total_chunks})",
            )
            next_report = done + max(1, total_chunks // 10)
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
    from whatwasthat.storage.raw_store import RawSpanStore
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()
    raw_store = RawSpanStore(_raw_spans_path(config))
    raw_store.initialize()
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
TS=$(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z)

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
TURN_ID=$(echo "$INPUT" | jq -r '.turn_id // empty')
PROJECT=$(basename "$CWD")

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "$TS source=codex-cli project=$PROJECT" \
         "session=$SESSION_ID status=skip_no_transcript" \
         "reason=missing_or_invalid_transcript" >> "$LOG"
    exit 0
fi

(
  echo "$TS source=codex-cli project=$PROJECT" \
       "session=$SESSION_ID turn=$TURN_ID" \
       "transcript=$TRANSCRIPT_PATH status=ingest_start"
  {wwt_path} ingest "$TRANSCRIPT_PATH" 2>&1
  TS_DONE=$(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z)
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
LOG="$HOME/.wwt/ingest.log"
TS=$(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z)

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
PROJECT=$(basename "$CWD")

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "$TS source=gemini-cli project=$PROJECT" \
         "session=$SESSION_ID status=skip_no_transcript" \
         "reason=missing_or_invalid_transcript" >> "$LOG"
    exit 0
fi

(
  echo "$TS source=gemini-cli project=$PROJECT" \
       "session=$SESSION_ID" \
       "transcript=$TRANSCRIPT_PATH status=ingest_start"
  {wwt_path} ingest "$TRANSCRIPT_PATH" 2>&1
  TS_DONE=$(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z)
  echo "$TS_DONE source=gemini-cli project=$PROJECT" \
       "session=$SESSION_ID status=ingest_done"
) >> "$LOG" &
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
def setup(
    with_memory: bool = typer.Option(
        False,
        "--with-memory",
        help=(
            "각 에이전트의 전역 메모리 파일(CLAUDE.md / GEMINI.md / AGENTS.md)에 "
            "WWT 사용 규칙 블록을 주입합니다. 블록 마커로 격리되어 있어 재실행 시 "
            "갱신되고, 마커 구간만 지우면 안전하게 제거할 수 있습니다."
        ),
    ),
) -> None:
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
    from whatwasthat.storage.raw_store import RawSpanStore
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()
    raw_store = RawSpanStore(_raw_spans_path(config))
    raw_store.initialize()
    typer.echo("✓ DB 초기화 완료")

    # 2. Stop Hook 스크립트 설치
    hooks_dir = Path.home() / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_script = hooks_dir / "wwt_auto_ingest.sh"

    wwt_path = shutil.which("wwt") or "wwt"

    hook_content = f"""#!/bin/bash
INPUT=$(cat)
LOG="$HOME/.wwt/ingest.log"
TS=$(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z)

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
PROJECT=$(basename "$CWD")

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "$TS source=claude-code project=$PROJECT" \
         "session=$SESSION_ID status=skip_no_transcript" \
         "reason=missing_or_invalid_transcript" >> "$LOG"
    exit 0
fi

(
  echo "$TS source=claude-code project=$PROJECT" \
       "session=$SESSION_ID" \
       "transcript=$TRANSCRIPT_PATH status=ingest_start"
  {wwt_path} ingest "$TRANSCRIPT_PATH" 2>&1
  TS_DONE=$(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z)
  echo "$TS_DONE source=claude-code project=$PROJECT" \
       "session=$SESSION_ID status=ingest_done"
) >> "$LOG" &
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

    # 5. Auto-ingest existing sessions per platform via the shared bulk helper.
    # BM25 rebuild is deferred to the last platform call for efficiency.
    _bulk_ingest_directory(
        vector,
        Path.home() / ".claude" / "projects",
        patterns=["**/*.jsonl"],
        label="Claude Code",
        raw_store=raw_store,
        rebuild_at_end=False,
    )
    _bulk_ingest_directory(
        vector,
        Path.home() / ".gemini" / "tmp",
        patterns=["**/chats/*.json"],
        label="Gemini CLI",
        raw_store=raw_store,
        rebuild_at_end=False,
    )
    _bulk_ingest_directory(
        vector,
        Path.home() / ".codex" / "sessions",
        patterns=["**/*.jsonl"],
        label="Codex CLI",
        raw_store=raw_store,
        rebuild_at_end=True,  # last platform: rebuild BM25 once at the very end
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

    # 8. (opt-in) 각 에이전트 전역 메모리에 WWT 사용 규칙 주입
    if with_memory:
        from whatwasthat.usage_guide import upsert_memory_block

        memory_targets = [
            ("Claude Code", Path.home() / ".claude" / "CLAUDE.md"),
            ("Gemini CLI", Path.home() / ".gemini" / "GEMINI.md"),
            ("Codex CLI", Path.home() / ".codex" / "AGENTS.md"),
        ]
        for label, target_path in memory_targets:
            status = upsert_memory_block(target_path)
            status_msg = {
                "created": "생성",
                "updated": "갱신",
                "appended": "블록 추가",
                "unchanged": "이미 최신",
            }.get(status, status)
            typer.echo(f"✓ {label} 메모리 {status_msg}: {target_path}")

    typer.echo("\n설정 완료! 각 플랫폼을 재시작하여 확인하세요.")


@app.command()
def ingest(path: str = typer.Argument(help="JSONL file or directory path")) -> None:
    """Ingest conversation logs into the vector store."""
    config = _get_config()
    file_path = Path(path).expanduser()

    from whatwasthat.pipeline.chunker import chunk_turns
    from whatwasthat.pipeline.parser import detect_parser
    from whatwasthat.storage.raw_store import RawSpanStore
    from whatwasthat.storage.vector import VectorStore

    vector = VectorStore(config.chroma_path)
    vector.initialize()
    raw_store = RawSpanStore(_raw_spans_path(config))
    raw_store.initialize()

    if file_path.is_dir():
        # Delegate to the shared bulk helper (parse + chunk + single upsert + BM25).
        _bulk_ingest_directory(
            vector,
            file_path,
            patterns=["**/*.jsonl", "**/*.json"],
            label=file_path.name or "ingest",
            raw_store=raw_store,
            rebuild_at_end=True,
        )
        return

    # Single file — keep incremental upsert path (change-detection benefit).
    parser = detect_parser(file_path)
    if parser is None:
        typer.echo(f"Unsupported file format: {file_path}")
        return
    session_id = file_path.stem
    turns = parser.parse_turns(file_path)
    if not turns:
        typer.echo("No turns parsed.")
        return
    meta = parser.parse_meta(file_path)
    spans, chunks = chunk_turns(turns, session_id=session_id, meta=meta)
    if not chunks:
        typer.echo("No chunks produced.")
        return
    raw_store.upsert_spans(spans)
    embedded = vector.upsert_session_chunks(session_id, chunks, rebuild_bm25=True)
    typer.echo(
        f"Done: 1 session, {len(spans)} spans, "
        f"{len(chunks)} chunks ({embedded} freshly embedded)",
    )


@app.command("remote-ingest")
def remote_ingest(
    env: str = typer.Option(..., "--env", help="원격 메모리 환경 이름"),
    date: str = typer.Option(..., "--date", help="KST 기준 수집 날짜 (YYYY-MM-DD)"),
    source: str = typer.Option(None, "--source", "-s", help="플랫폼 필터"),
    all_projects: bool = typer.Option(
        False,
        "--all-projects",
        help="현재 cwd 대신 모든 프로젝트 업로드 허용",
    ),
) -> None:
    """현재 프로젝트 기본 범위로 원격 메모리 게이트웨이에 업로드."""
    project = None if all_projects else _current_project_name()
    _run_remote_ingest_for_date(env=env, date=date, source=source, project=project)


@app.command("remote-ingest-all")
def remote_ingest_all(
    env: str = typer.Option(..., "--env", help="원격 메모리 환경 이름"),
    source: str = typer.Option(..., "--source", "-s", help="플랫폼 필터"),
) -> None:
    """특정 source의 세션을 전체 프로젝트 범위에서 원격 업로드."""
    _run_remote_ingest_all(env=env, source=source)


@app.command()
def migrate() -> None:
    """Backfill missing timestamp_epoch metadata on existing chunks.

    Scans every stored chunk and, for any that has timestamp_epoch=0 but a
    non-empty ISO timestamp field, back-computes the epoch and updates metadata
    in place. No re-embedding — only metadata update via collection.update.
    """
    from datetime import datetime

    from whatwasthat.storage.vector import VectorStore
    from whatwasthat.timeutil import to_epoch

    config = _get_config()
    vector = VectorStore(config.chroma_path)
    vector.initialize()
    coll = vector._get_collection()

    total = coll.count()
    if total == 0:
        typer.echo("No chunks to migrate.")
        return

    typer.echo(f"Scanning {total} chunks for missing timestamp_epoch...")
    all_data = coll.get(include=["metadatas"])
    ids = all_data.get("ids") or []
    metas = all_data.get("metadatas") or []

    to_update_ids: list[str] = []
    to_update_metas: list[dict] = []
    for cid, meta in zip(ids, metas):
        if meta is None:
            continue
        current_epoch = int(meta.get("timestamp_epoch", 0) or 0)
        if current_epoch != 0:
            continue
        iso = meta.get("timestamp", "")
        if not iso:
            continue
        try:
            ts = datetime.fromisoformat(iso)
        except ValueError:
            continue
        new_meta = dict(meta)
        new_meta["timestamp_epoch"] = to_epoch(ts)
        to_update_ids.append(cid)
        to_update_metas.append(new_meta)

    if not to_update_ids:
        typer.echo("All chunks already have timestamp_epoch populated.")
        return

    coll.update(ids=to_update_ids, metadatas=to_update_metas)
    typer.echo(f"✓ Backfilled {len(to_update_ids)}/{total} chunks.")


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
    date: str = typer.Option(
        None, "--date", "-d", help="날짜 필터 (YYYY-MM-DD, Asia/Seoul)",
    ),
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
        query, project=filter_project, source=source, git_branch=branch,
        mode=mode, date=date,
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
            typer.echo(
                f"     [chunk:{chunk.id} | span:{chunk.span_id} | "
                f"turns {chunk.start_turn_index}-{chunk.end_turn_index}]",
            )
            lines = chunk.raw_preview.strip().split("\n")[:2]
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
            typer.echo(
                f"     [chunk:{chunk.id} | span:{chunk.span_id} | "
                f"turns {chunk.start_turn_index}-{chunk.end_turn_index}]",
            )
            lines = chunk.raw_preview.strip().split("\n")[:2]
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
    raw_dir = _raw_spans_path(config).parent
    bm25_dir = config.bm25_index_path.parent

    targets = [p for p in (vector_dir, raw_dir, bm25_dir) if p.exists()]
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
    typer.echo("✓ 모든 적재 데이터 삭제 완료 (vector + raw + bm25)")
    typer.echo("  다시 적재하려면: wwt setup 또는 wwt ingest <경로>")
