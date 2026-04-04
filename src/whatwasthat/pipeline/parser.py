"""대화 로그 파싱 - JSONL 파일을 Turn 리스트로 변환."""

import json
import re
from datetime import datetime
from pathlib import Path

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
    """디렉토리 내 모든 JSONL 세션 파일을 파싱."""
    results: dict[str, list[Turn]] = {}
    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
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
