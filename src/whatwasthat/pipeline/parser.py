"""대화 로그 파싱 - JSONL 파일을 Turn 리스트로 변환."""

import json
from pathlib import Path

from whatwasthat.models import Turn

_ALLOWED_TYPES = {"user", "assistant"}


def _extract_text(content: str | list[dict]) -> str:
    """content 필드에서 텍스트만 추출."""
    if isinstance(content, str):
        return content
    text_parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block["text"])
    return "\n".join(text_parts)


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
            if text:
                turns.append(Turn(role=role, content=text))
    return turns


def parse_session_dir(session_dir: Path) -> dict[str, list[Turn]]:
    """디렉토리 내 모든 JSONL 세션 파일을 파싱."""
    results: dict[str, list[Turn]] = {}
    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        session_id = jsonl_file.stem
        results[session_id] = parse_jsonl(jsonl_file)
    return results
