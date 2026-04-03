"""대화 로그 파싱 - JSONL 파일을 Turn 리스트로 변환."""

from pathlib import Path

from whatwasthat.models import Turn


def parse_jsonl(file_path: Path) -> list[Turn]:
    """Claude Code JSONL 대화 로그를 파싱하여 Turn 리스트로 변환."""
    pass


def parse_session_dir(session_dir: Path) -> dict[str, list[Turn]]:
    """디렉토리 내 모든 JSONL 세션 파일을 파싱."""
    pass
