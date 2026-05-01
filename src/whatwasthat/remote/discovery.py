"""원격 업로드용 로컬 세션 discovery."""

from __future__ import annotations

from pathlib import Path

from whatwasthat.pipeline.parser import ClaudeCodeParser, CodexCliParser, GeminiCliParser
from whatwasthat.remote.models import DiscoveredSession
from whatwasthat.timeutil import kst_day_bounds, to_epoch

_SOURCE_ROOTS: dict[str, Path] = {
    "claude-code": Path.home() / ".claude" / "projects",
    "gemini-cli": Path.home() / ".gemini" / "tmp",
    "codex-cli": Path.home() / ".codex" / "sessions",
}

_PARSERS = {
    "claude-code": ClaudeCodeParser(),
    "gemini-cli": GeminiCliParser(),
    "codex-cli": CodexCliParser(),
}


def _infer_project(path: Path, source: str, root: Path) -> str:
    if source == "gemini-cli":
        try:
            rel = path.relative_to(root)
            if rel.parts:
                return rel.parts[0]
        except ValueError:
            return ""
    return ""


def _build_discovered_session(
    *,
    env: str,
    source_name: str,
    root: Path,
    path: Path,
) -> DiscoveredSession | None:
    parser = _PARSERS[source_name]
    meta = parser.parse_meta(path)
    project = ""
    project_path = ""
    git_branch = ""
    started_at = None
    original_session_id = path.stem

    if meta is not None:
        project = meta.project
        project_path = meta.project_path
        git_branch = meta.git_branch
        started_at = meta.started_at
        original_session_id = meta.session_id or original_session_id

    if not project:
        project = _infer_project(path, source_name, root)
    if not project_path and project:
        project_path = str(Path.home() / project)
    if started_at is None:
        return None

    return DiscoveredSession(
        env=env,
        source=source_name,
        project=project,
        project_path=project_path,
        git_branch=git_branch,
        original_session_id=original_session_id,
        filename=path.name,
        started_at=started_at,
        transcript_text=path.read_text(encoding="utf-8"),
        path=path,
        meta=meta,
    )


def _iter_sessions(*, env: str, sources: list[str]) -> list[DiscoveredSession]:
    sessions: list[DiscoveredSession] = []
    for source_name in sources:
        parser = _PARSERS.get(source_name)
        root = _SOURCE_ROOTS.get(source_name)
        if parser is None or root is None or not root.exists():
            continue
        for path in parser.discover_sessions(root).values():
            session = _build_discovered_session(
                env=env,
                source_name=source_name,
                root=root,
                path=path,
            )
            if session is not None:
                sessions.append(session)
    return sessions


def collect_sessions_for_date(
    *,
    env: str,
    date: str,
    source: str | None = None,
    project: str | None = None,
) -> list[DiscoveredSession]:
    """KST 날짜 기준으로 source/project 필터된 세션 수집."""
    start_epoch, end_epoch = kst_day_bounds(date)
    sources = [source] if source else list(_PARSERS)
    sessions: list[DiscoveredSession] = []

    for session in _iter_sessions(env=env, sources=sources):
        if project and session.project != project:
            continue
        started_epoch = to_epoch(session.started_at)
        if start_epoch <= started_epoch < end_epoch:
            sessions.append(session)

    return sessions


def collect_all_sessions_for_source(*, env: str, source: str) -> list[DiscoveredSession]:
    """특정 source의 전체 세션 수집."""
    return _iter_sessions(env=env, sources=[source])


def discover_sessions(
    *,
    source: str | None = None,
    project: str | None = None,
) -> list[DiscoveredSession]:
    """기존 호출자 호환용 discovery 엔트리."""
    sessions = _iter_sessions(env="", sources=[source] if source else list(_PARSERS))
    if project is None:
        return sessions
    return [session for session in sessions if session.project == project]
