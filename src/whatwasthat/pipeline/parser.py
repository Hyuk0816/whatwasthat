"""대화 로그 파싱 - JSONL 파일을 Turn 리스트로 변환."""

import json
import re
from pathlib import Path

from whatwasthat.models import Turn

_ALLOWED_TYPES = {"user", "assistant"}

# 코드 블록 제거 패턴
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
# HTML/XML 태그 제거 패턴
_TAG_RE = re.compile(r"<[^>]+>")
# 의미 없는 짧은 턴 필터
_SKIP_PATTERNS = [
    r"^\[Request interrupted",
    r"^확인합니다",
    r"^진행하겠습니다",
    r"^계속하겠습니다",
    r"^실패한 것입니다",
]
_SKIP_RE = re.compile("|".join(_SKIP_PATTERNS))

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
    # HTML/XML 태그 제거
    cleaned = _TAG_RE.sub("", cleaned)
    # 연속 공백/줄바꿈 정리
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # assistant 응답은 길이 제한
    if role == "assistant" and len(cleaned) > _MAX_CONTENT_LEN:
        cleaned = cleaned[:_MAX_CONTENT_LEN] + "..."
    return cleaned


def _is_meaningful(text: str) -> bool:
    """의미 있는 턴인지 판단."""
    if len(text) < 5:
        return False
    if _SKIP_RE.search(text):
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
            if _is_meaningful(cleaned):
                turns.append(Turn(role=role, content=cleaned))
    return turns


def parse_session_dir(session_dir: Path) -> dict[str, list[Turn]]:
    """디렉토리 내 모든 JSONL 세션 파일을 파싱."""
    results: dict[str, list[Turn]] = {}
    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        session_id = jsonl_file.stem
        results[session_id] = parse_jsonl(jsonl_file)
    return results
