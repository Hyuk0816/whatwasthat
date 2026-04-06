"""대화 로그 파싱 - JSONL 파일을 Turn 리스트로 변환."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Protocol

from whatwasthat.models import SessionMeta, Turn

_ALLOWED_TYPES = {"user", "assistant"}

# 코드 블록 제거 패턴
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
# 시스템 블록 전체 제거 (태그 + 내용)
_SYSTEM_BLOCK_RE = re.compile(
    r"<(system-reminder|command-name|command-message|command-args"
    r"|local-command-stdout|local-command-caveat|EXTREMELY_IMPORTANT"
    r"|session-restore|antml:[\w:]+)>[\s\S]*?</\1>",
    re.IGNORECASE,
)
# 남은 HTML/XML 태그 제거
_TAG_RE = re.compile(r"<[^>]+>")
# 의미 없는 짧은 턴 필터
_SKIP_PATTERNS = [
    r"^\[Request interrupted",
    r"^확인합니다",
    r"^진행하겠습니다",
    r"^계속하겠습니다",
    r"^실패한 것입니다",
    # 스킬/시스템 확장 내용
    r"^# /\w+",
    r"^## 실행 단계",
    r"^### Step \d+",
]
_SKIP_RE = re.compile("|".join(_SKIP_PATTERNS))

# 짧은 assistant 상태 메시지 (80자 미만일 때만 적용)
_SHORT_OP_RE = re.compile(
    r"하겠습니다\.?\s*$|완료되었습니다|실패합니다|변경 완료"
)

# assistant 응답 최대 길이 (코드 제거 후)
_MAX_CONTENT_LEN = 500


def _extract_text(content: str | list[dict]) -> str:
    """content 필드에서 텍스트만 추출."""
    if isinstance(content, str):
        return content
    text_parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block["text"])
    return "\n".join(text_parts)


def _clean_content(text: str, role: str) -> str:
    """노이즈 제거: 코드 블록, 태그, 긴 응답 축약."""
    # 코드 블록 제거
    cleaned = _CODE_BLOCK_RE.sub("", text)
    # 시스템 블록 전체 제거 (태그 + 내용)
    cleaned = _SYSTEM_BLOCK_RE.sub("", cleaned)
    # 남은 HTML/XML 태그 제거
    cleaned = _TAG_RE.sub("", cleaned)
    # 연속 공백/줄바꿈 정리
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # assistant 응답은 길이 제한
    if role == "assistant" and len(cleaned) > _MAX_CONTENT_LEN:
        cleaned = cleaned[:_MAX_CONTENT_LEN] + "..."
    return cleaned


def _is_meaningful(text: str, role: str = "") -> bool:
    """의미 있는 턴인지 판단."""
    if len(text) < 5:
        return False
    if _SKIP_RE.search(text):
        return False
    # 짧은 assistant 상태 메시지 필터
    if role == "assistant" and len(text) < 80 and _SHORT_OP_RE.search(text):
        return False
    return True


def parse_jsonl(file_path: Path) -> list[Turn]:
    """Claude Code JSONL 대화 로그를 파싱하여 Turn 리스트로 변환."""
    turns: list[Turn] = []
    if not file_path.exists() or file_path.stat().st_size == 0:
        return turns

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("type") not in _ALLOWED_TYPES:
                continue
            msg = obj.get("message", {})
            role = msg.get("role", "")
            raw_content = msg.get("content", "")
            text = _extract_text(raw_content)
            if not text:
                continue
            cleaned = _clean_content(text, role)
            if _is_meaningful(cleaned, role=role):
                turns.append(Turn(role=role, content=cleaned))
    return turns


def parse_session_dir(session_dir: Path) -> dict[str, list[Turn]]:
    """디렉토리 내 모든 JSONL 세션 파일을 재귀적으로 파싱."""
    results: dict[str, list[Turn]] = {}
    for jsonl_file in sorted(session_dir.rglob("*.jsonl")):
        session_id = jsonl_file.stem
        results[session_id] = parse_jsonl(jsonl_file)
    return results


def parse_session_meta(file_path: Path) -> SessionMeta | None:
    """JSONL 파일에서 세션 메타데이터를 추출."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return None

    session_id: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    started_at: datetime | None = None

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if session_id is None:
                session_id = obj.get("sessionId")
            if cwd is None:
                cwd = obj.get("cwd")
            if git_branch is None:
                git_branch = obj.get("gitBranch")
            if started_at is None:
                ts = obj.get("timestamp")
                if ts:
                    started_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if session_id and cwd and git_branch and started_at:
                break

    if not (session_id and cwd and git_branch and started_at):
        return None

    project = Path(cwd).name
    return SessionMeta(
        session_id=session_id,
        project=project,
        project_path=cwd,
        git_branch=git_branch,
        started_at=started_at,
    )


# ---------------------------------------------------------------------------
# SessionParser Protocol + 구현체
# ---------------------------------------------------------------------------

class SessionParser(Protocol):
    """대화 로그 파서 공통 인터페이스."""

    @property
    def source(self) -> str: ...
    def can_parse(self, file_path: Path) -> bool: ...
    def parse_turns(self, file_path: Path) -> list[Turn]: ...
    def parse_meta(self, file_path: Path) -> SessionMeta | None: ...
    def discover_sessions(self, directory: Path) -> dict[str, Path]: ...


class ClaudeCodeParser:
    """Claude Code JSONL 대화 로그 파서."""

    @property
    def source(self) -> str:
        return "claude-code"

    def can_parse(self, file_path: Path) -> bool:
        if file_path.suffix != ".jsonl":
            return False
        try:
            with file_path.open("r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if not first_line:
                    return False
                obj = json.loads(first_line)
                return "sessionId" in obj or obj.get("type") in _ALLOWED_TYPES
        except (json.JSONDecodeError, OSError):
            return False

    def parse_turns(self, file_path: Path) -> list[Turn]:
        turns = parse_jsonl(file_path)
        for t in turns:
            t.source = self.source
        return turns

    def parse_meta(self, file_path: Path) -> SessionMeta | None:
        meta = parse_session_meta(file_path)
        if meta:
            meta.source = self.source
        return meta

    def discover_sessions(self, directory: Path) -> dict[str, Path]:
        return {f.stem: f for f in sorted(directory.rglob("*.jsonl")) if self.can_parse(f)}


# Role 정규화 매핑 (Gemini → 내부 표준)
_GEMINI_ROLE_MAP: dict[str, str] = {
    "model": "assistant",
    "gemini": "assistant",
    "user": "user",
}


class GeminiCliParser:
    """Gemini CLI 대화 로그 파서 (JSON + JSONL 지원)."""

    @property
    def source(self) -> str:
        return "gemini-cli"

    def can_parse(self, file_path: Path) -> bool:
        if file_path.suffix == ".json":
            return self._can_parse_json(file_path)
        if file_path.suffix == ".jsonl":
            return self._can_parse_jsonl(file_path)
        return False

    def _can_parse_json(self, file_path: Path) -> bool:
        """JSON 포맷: 최상위에 "contents" 키가 있으면 Gemini."""
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return isinstance(data, dict) and "contents" in data
        except (json.JSONDecodeError, OSError):
            return False

    def _can_parse_jsonl(self, file_path: Path) -> bool:
        """JSONL 포맷: session_metadata 또는 Gemini 형식 턴 감지."""
        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    # session_metadata → Gemini 확정
                    if obj.get("type") == "session_metadata":
                        return True
                    # Claude Code는 "message" 키를 가짐 → 제외
                    if "message" in obj:
                        return False
                    obj_type = obj.get("type", "")
                    # Gemini JSONL: type in (user, gemini) AND content가 list
                    if obj_type in ("user", "gemini") and isinstance(
                        obj.get("content"), list
                    ):
                        return True
            return False
        except (json.JSONDecodeError, OSError):
            return False

    def parse_turns(self, file_path: Path) -> list[Turn]:
        if file_path.suffix == ".json":
            return self._parse_json(file_path)
        if file_path.suffix == ".jsonl":
            return self._parse_jsonl(file_path)
        return []

    def _parse_json(self, file_path: Path) -> list[Turn]:
        """Gemini JSON 포맷 파싱: contents[].role + parts[].text 추출."""
        turns: list[Turn] = []
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return turns

        for entry in data.get("contents", []):
            raw_role = entry.get("role", "")
            role = _GEMINI_ROLE_MAP.get(raw_role, raw_role)
            if role not in ("user", "assistant"):
                continue

            # parts에서 text 키가 있는 항목만 추출 (functionCall/functionResponse 제외)
            text_parts: list[str] = []
            for part in entry.get("parts", []):
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])

            if not text_parts:
                continue

            text = "\n".join(text_parts)
            cleaned = _clean_content(text, role)
            if _is_meaningful(cleaned, role=role):
                turns.append(Turn(role=role, content=cleaned, source=self.source))

        return turns

    def _parse_jsonl(self, file_path: Path) -> list[Turn]:
        """Gemini JSONL 포맷 파싱: type in (user, gemini) + content[].text 추출."""
        turns: list[Turn] = []
        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    obj_type = obj.get("type", "")
                    if obj_type not in ("user", "gemini"):
                        continue

                    role = _GEMINI_ROLE_MAP.get(obj_type, obj_type)

                    # content 배열에서 text 추출
                    text_parts: list[str] = []
                    for item in obj.get("content", []):
                        if isinstance(item, dict) and "text" in item:
                            text_parts.append(item["text"])

                    if not text_parts:
                        continue

                    text = "\n".join(text_parts)
                    cleaned = _clean_content(text, role)
                    if _is_meaningful(cleaned, role=role):
                        turns.append(
                            Turn(role=role, content=cleaned, source=self.source)
                        )
        except (json.JSONDecodeError, OSError):
            pass

        return turns

    def parse_meta(self, file_path: Path) -> SessionMeta | None:
        if file_path.suffix == ".json":
            return self._parse_meta_json(file_path)
        if file_path.suffix == ".jsonl":
            return self._parse_meta_jsonl(file_path)
        return None

    def _parse_meta_json(self, file_path: Path) -> SessionMeta | None:
        """JSON 포맷에서 메타데이터 추출 (파일명 기반 session_id)."""
        turns = self._parse_json(file_path)
        if not turns:
            return None
        return SessionMeta(
            session_id=file_path.stem,
            project="",
            project_path="",
            git_branch="",
            started_at=datetime.now(),
            turn_count=len(turns),
            source=self.source,
        )

    def _parse_meta_jsonl(self, file_path: Path) -> SessionMeta | None:
        """JSONL 포맷에서 session_metadata 행으로부터 메타데이터 추출."""
        session_id: str | None = None
        started_at: datetime | None = None

        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if obj.get("type") == "session_metadata":
                        session_id = obj.get("sessionId")
                        start_time = obj.get("startTime")
                        if start_time:
                            started_at = datetime.fromisoformat(
                                start_time.replace("Z", "+00:00")
                            )
                        break
        except (json.JSONDecodeError, OSError):
            return None

        if not session_id:
            session_id = file_path.stem
        if not started_at:
            started_at = datetime.now()

        turns = self._parse_jsonl(file_path)
        return SessionMeta(
            session_id=session_id,
            project="",
            project_path="",
            git_branch="",
            started_at=started_at,
            turn_count=len(turns),
            source=self.source,
        )

    def discover_sessions(self, directory: Path) -> dict[str, Path]:
        results: dict[str, Path] = {}
        for pattern in ("**/*.json", "**/*.jsonl"):
            for f in sorted(directory.glob(pattern)):
                if self.can_parse(f):
                    results[f.stem] = f
        return results


_PARSERS: list[SessionParser] = [GeminiCliParser(), ClaudeCodeParser()]


def detect_parser(file_path: Path) -> SessionParser | None:
    """파일을 분석하여 적합한 파서를 자동 감지."""
    for parser in _PARSERS:
        if parser.can_parse(file_path):
            return parser
    return None
