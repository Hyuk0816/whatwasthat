"""WWT 사용 규칙 — MCP instructions와 agent 메모리 파일에서 공통 사용."""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# 트리거 카탈로그 — 이 한 곳만 수정하면 MCP instructions + 메모리 블록 모두 반영됨
# ---------------------------------------------------------------------------

_TRIGGERS: list[tuple[str, list[str], str]] = [
    (
        "세션 시작 직후 일반 맥락 파악",
        [
            "어제 이 프로젝트 어디까지 했지?",
            "지금 상황 파악해줘",
            "이어서 작업하자",
            "맥락 파악해",
        ],
        "search_memory(query='recent technical decisions and architecture choices')",
    ),
    (
        "모호한 과거 회수",
        [
            "그때 그거 뭐였지?",
            "이전에 어떻게 했지?",
            "지난번에 뭐라고 했지?",
        ],
        "search_memory(query='<질문에서 추출한 핵심 키워드>')",
    ),
    (
        "의사결정 이유",
        [
            "왜 Redis를 골랐지?",
            "왜 A 대신 B로 갔지?",
            "이유가 뭐였지?",
        ],
        "search_decision(query='...')",
    ),
    (
        "크로스 에이전트 회수",
        [
            "codex/claude/gemini에서 작업한거 파악해",
            "어제 Codex로 한 작업 보여줘",
            "Gemini로 만든 그 설정",
        ],
        "search_memory(query='...', source='codex-cli' | 'claude-code' | 'gemini-cli')",
    ),
    (
        "크로스 프로젝트 회수",
        [
            "다른 프로젝트에서 비슷한 문제 어떻게 풀었지?",
            "이 패턴 다른 레포에서 본 적 있는데",
        ],
        "search_all(query='...')",
    ),
    (
        "특정 날짜 조회",
        [
            "어제 뭐 했지?",
            "2026-04-11에 한 작업",
        ],
        "모든 search 도구에 date='YYYY-MM-DD' (Asia/Seoul) 전달",
    ),
]


def _format_trigger_markdown() -> str:
    """메모리 파일(Markdown)용 트리거 리스트."""
    lines: list[str] = []
    for idx, (label, examples, action) in enumerate(_TRIGGERS, 1):
        quoted = ", ".join(f'"{example}"' for example in examples)
        lines.append(f"{idx}. **{label}** — {quoted}")
        lines.append(f"   → `{action}`")
    return "\n".join(lines)


def _format_trigger_inline() -> str:
    """MCP instructions(plain text)용 트리거 리스트."""
    lines: list[str] = []
    for idx, (label, examples, action) in enumerate(_TRIGGERS, 1):
        quoted = ", ".join(f"'{example}'" for example in examples)
        lines.append(f"{idx}) {label} — 예: {quoted} → {action}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP 서버 instructions — FastMCP 초기화 시 주입
# ---------------------------------------------------------------------------

USAGE_GUIDE_INLINE: str = (
    "WWT(whatwasthat)는 Claude Code / Gemini CLI / Codex CLI의 과거 대화 기억을 통합 검색합니다.\n"
    "아래 트리거가 오면 반드시 다른 도구(git log, Bash, Read)보다 먼저 WWT를 호출하세요.\n\n"
    "[선제 호출 트리거]\n"
    f"{_format_trigger_inline()}\n\n"
    "[검색 이후]\n"
    "- preview로 답이 부족하면 recall_chunk(chunk_id='...')로 원문 확장\n"
    "- include_neighbors=N으로 앞뒤 span까지 함께 회수\n\n"
    "[도구 선택]\n"
    "- search_memory  : 현재 프로젝트 + 필터 기반 검색 (기본)\n"
    "- search_all     : 모든 프로젝트/플랫폼 통합 검색\n"
    "- search_decision: 의사결정 맥락(왜 A 대신 B)에 특화\n"
    "- recall_chunk   : chunk_id로 원문 + 코드 스니펫 완전 조회\n"
    "- ingest_session : 로그 경로 수동 색인"
)


# ---------------------------------------------------------------------------
# Agent 메모리 파일 블록 — `wwt setup --with-memory`로 주입
# ---------------------------------------------------------------------------

MEMORY_BLOCK_START = "<!-- wwt:begin -->"
MEMORY_BLOCK_END = "<!-- wwt:end -->"

USAGE_GUIDE_MARKDOWN: str = f"""{MEMORY_BLOCK_START}
## WWT (whatwasthat) 사용 규칙

이 머신에는 WWT MCP 서버가 등록되어 있다. 아래 트리거가 오면 **다른 도구(git log, Bash, Read)보다 먼저** WWT를 호출한다.

### 선제 호출 트리거
{_format_trigger_markdown()}

### 검색 이후
- preview로 답이 부족하면 `recall_chunk(chunk_id='...')`로 원문 확장
- `include_neighbors=N`으로 앞뒤 span까지 함께 회수

### 우선순위
WWT 검색 결과가 있으면 그 위에 git log / work-plan / 파일 Read를 보강용으로 얹는다. WWT가 빈 결과를 주면 그때 다른 도구로 넘어간다.

### 도구 선택
- `search_memory`  : 현재 프로젝트 + 필터 기반 검색 (기본)
- `search_all`     : 모든 프로젝트/플랫폼 통합 검색
- `search_decision`: 의사결정 맥락(왜 A 대신 B)에 특화
- `recall_chunk`   : chunk_id로 원문 + 코드 스니펫 완전 조회
- `ingest_session` : 로그 경로 수동 색인

### 블록 관리
이 블록은 `wwt setup --with-memory`가 생성했다. 같은 명령을 다시 실행하면 최신 규칙으로 갱신되고, 제거하려면 `{MEMORY_BLOCK_START}`부터 `{MEMORY_BLOCK_END}`까지 삭제하면 된다.
{MEMORY_BLOCK_END}
"""


# ---------------------------------------------------------------------------
# 메모리 블록 주입 헬퍼
# ---------------------------------------------------------------------------

_BLOCK_PATTERN = re.compile(
    re.escape(MEMORY_BLOCK_START) + r".*?" + re.escape(MEMORY_BLOCK_END),
    re.DOTALL,
)


def upsert_memory_block(path: Path) -> str:
    """Agent 메모리 파일에 WWT 블록을 idempotent하게 쓴다.

    Returns:
        상태 문자열: "created" | "updated" | "unchanged" | "appended"
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    block = USAGE_GUIDE_MARKDOWN.rstrip() + "\n"

    if not path.exists():
        path.write_text(block)
        return "created"

    existing = path.read_text()
    if MEMORY_BLOCK_START in existing and MEMORY_BLOCK_END in existing:
        replaced = _BLOCK_PATTERN.sub(block.rstrip(), existing)
        if replaced == existing:
            return "unchanged"
        # 끝에 개행 보장
        if not replaced.endswith("\n"):
            replaced += "\n"
        path.write_text(replaced)
        return "updated"

    # 마커가 없으면 파일 끝에 append
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    path.write_text(existing + block)
    return "appended"


def remove_memory_block(path: Path) -> bool:
    """WWT 블록을 제거한다. 변경이 있었으면 True."""
    if not path.exists():
        return False
    existing = path.read_text()
    if MEMORY_BLOCK_START not in existing or MEMORY_BLOCK_END not in existing:
        return False
    stripped = _BLOCK_PATTERN.sub("", existing)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).rstrip() + "\n"
    path.write_text(stripped)
    return True
