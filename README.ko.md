# WWT — 모든 AI 에이전트를 위한 하나의 뇌

> **에이전트들이 하나의 뇌를 공유합니다. 같은 설명을 반복하거나 .md 파일을 잔뜩 쓰는 일을 멈추세요.**

[![PyPI version](https://badge.fury.io/py/whatwasthat.svg)](https://pypi.org/project/whatwasthat/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**지원 에이전트:** Claude Code · Gemini CLI · Codex CLI
**[English README](README.md)**

---

## WWT는 무엇을 하는가

코딩 에이전트 셋. 로그 포맷 셋. 세션이 끝나면 사라지는 메모리 셋.
WWT는 이 셋을 **모든 에이전트가 읽을 수 있는 하나의 검색 가능한 뇌**로 합칩니다.

```
Claude Code ─┐
Gemini CLI  ─┼──→  로컬 인덱스 1개  ──→  어떤 에이전트도 회수 가능
Codex CLI   ─┘
```

같은 컨텍스트를 다시 설명할 필요 없습니다. `CLAUDE.md` 묘지도 필요 없습니다. *"잠깐, 내가 왜 Postgres를 골랐더라?"* 같은 순간도 없습니다.

## 빠른 시작

```bash
pip install whatwasthat              # 또는: uv tool install whatwasthat
wwt setup                            # 설치된 모든 에이전트의 DB + Hook + MCP 한 번에
```

끝입니다. 기존 로그는 자동으로 적재되고, 이후 세션은 종료 시 자동 캡처됩니다.

## 동작 원리

세션이 끝나면 에이전트의 Hook이 발동됩니다. WWT는 로그를 파싱하고, 코드를 추출하고, 대화를 청킹하고, 검색용 텍스트를 로컬에서 임베딩한 뒤(API 호출 없음) ChromaDB에 저장하고, 전체 원문 span은 SQLite에 보존합니다.

*"전에 X 어떻게 했었지?"* 라고 물으면 — 어떤 에이전트든 MCP를 통해 `search_memory`를 호출해 간결한 미리보기를 받고, 필요한 청크만 `recall_chunk`로 원문 확장합니다. *무엇*을 했는지뿐 아니라, *왜* 그렇게 했는지까지 포함해서.

```
세션 종료 → Hook → 파싱 → 청킹 → 임베딩 → ChromaDB + 원문 SQLite
질문         → MCP  → 검색 → 점수 → 미리보기 → 필요 시 원문 회수
```

## v1.0.12 업그레이드

v1.0.12는 전체 원문과 코드 스니펫을 보존하기 위해 저장 구조가 바뀝니다. 업그레이드 후 한 번 재적재하세요:

```bash
wwt reset --force
wwt setup
```

## 왜 하나의 뇌가 중요한가

| WWT 없이 | WWT와 함께 |
|---|---|
| 매 세션마다 에이전트가 망각 | 모든 에이전트에 걸친 영구 기억 |
| 매 세션마다 컨텍스트를 다시 설명 | 에이전트가 *왜*를 자동으로 회수 |
| `.md` 파일이 읽히지 않은 채 쌓임 | 대화 자체가 진실의 원천 |
| Claude는 Gemini가 어제 한 일을 못 봄 | 어떤 에이전트도 다른 에이전트의 기록을 읽음 |

## 검색 모드

| MCP 도구 | 에이전트가 호출하는 시점 |
|---|---|
| `search_memory` | "전에 Redis 어떻게 설정했었지?" |
| `search_decision` | "왜 Memcached 대신 Redis였지?" |
| `search_all` | 크로스 프로젝트, 크로스 에이전트 회수 |
| `recall_chunk` | 검색 결과의 `chunk_id`로 전체 원문과 코드 스니펫 조회 |

`search_memory`는 **자동 라우팅**됩니다 — 프로젝트 필터가 충분한 결과를 못 내면, 자동으로 전체 프로젝트로 확장합니다 (Self-ROUTE, EMNLP 2024). 한 번의 호출, 재시도 없음.

## 회수의 세 가지 방식

**1. 크로스 플랫폼** — *Claude가 어제 Codex가 한 일을 읽기*
```
사용자 (Claude Code에서):  "어젯밤에 JWT refresh token 어떻게 설정했지?"
WWT:                      [codex-cli] backend-api @ 2026-04-07 23:40 에서 발견
                          → Claude가 원본 Codex 대화를 읽고 답변.
```

**2. 크로스 프로젝트** — *다른 프로젝트의 해결책 재사용*
```
사용자 (frontend 프로젝트에서):  "다른 프로젝트에서 mTLS cert chain 어떻게 풀었더라?"
WWT:                            [claude-code] infra-gateway (main) @ 2026-03-22 에서 발견
                                → 같은 해결책, 다른 레포. 몇 초 만에 회수.
```

**3. 둘 다 동시에** — *크로스 플랫폼 AND 크로스 프로젝트*
```
사용자 (ml-pipeline 프로젝트, Gemini CLI):  "지난달에 왜 Kafka 빼고 NATS로 갔지?"
WWT search_decision:                       [claude-code] data-platform @ 2026-03-15 에서 발견
                                           → Claude가 다른 프로젝트에서 내린 결정을,
                                             이제 이 프로젝트의 Gemini에서 답변 가능.
```

## 스스로 강화되는 기억

사람의 spaced repetition에서 영감: 자주 회수되는 청크는 더 천천히 감쇠합니다. 실제로 다시 쓰는 결정은 선명하게 남고, 일회성 잡담은 옅어집니다.

여기에 3축 스코어링(Generative Agents, Stanford 2023):

```
final = relevance × (recency + importance)
```

오래된 핵심 결정이 최근 잡담을 이깁니다. 기억은 원래 그렇게 작동해야 합니다.

## 설치

```bash
pip install whatwasthat              # pip
uv tool install whatwasthat          # uv (권장)
```

그 다음 `wwt setup` 한 번. 머신에 이미 설치된 모든 에이전트(Claude Code, Gemini CLI, Codex CLI)에 MCP 서버를 등록하고 자동 캡처 Hook을 설치합니다. 여러 번 실행해도 안전합니다.

## 요구사항

- **Python** 3.10+
- **OS** macOS, Linux (Windows 미테스트)
- **디스크** ~200MB 설치 + ~470MB 임베딩 모델
- **네트워크** 모델 다운로드 후 100% 로컬. API 키 없음. 텔레메트리 없음.

## 문서

- [ARCHITECTURE.md](ARCHITECTURE.md) — 시스템 설계, 검색 엔진 내부
- [CLI_REFERENCE.md](CLI_REFERENCE.md) — 모든 CLI 명령과 플래그
- [MCP_REFERENCE.md](MCP_REFERENCE.md) — MCP 도구 시그니처와 예제

## 기여

```bash
uv run pytest tests/ -v
uv run ruff check src/
```

## 라이선스

[Apache License 2.0](LICENSE)
