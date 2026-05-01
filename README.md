# WWT — 모든 AI 에이전트를 위한 하나의 뇌

> **에이전트들이 하나의 뇌를 공유합니다. 같은 설명을 반복하거나 .md 파일 무한 생성을 멈추세요.**

[![PyPI version](https://badge.fury.io/py/whatwasthat.svg)](https://pypi.org/project/whatwasthat/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**지원 에이전트:** Claude Code · Gemini CLI · Codex CLI
**[English README](README.en.md)**

---

## WWT는 무엇을 하는가

코딩 에이전트 셋. 로그 포맷 셋. 세션이 끝나면 사라지는 메모리 셋.
WWT는 이 셋을 **모든 에이전트가 읽을 수 있는 하나의 검색 가능한 뇌**로 합칩니다.

```
Claude Code ─┐
Gemini CLI  ─┼──→  로컬 인덱스 1개  ──→  어떤 에이전트도 회수 가능
Codex CLI   ─┘
```

같은 컨텍스트를 다시 설명할 필요 없습니다. `CLAUDE.md` 묘지도 필요 없습니다. *"잠깐, 얘가 왜 이렇게 했지?"* 같은 순간도 없습니다.
그그그그 뭐였지?!를 해결하는 MCP 

## 빠른 시작

```bash
pip install whatwasthat              # 또는: uv tool install whatwasthat
wwt setup                            # 설치된 모든 에이전트의 DB + Hook + MCP 한 번에
```

끝입니다. 기존 로그는 자동으로 적재되고, 이후 세션은 종료 시 자동 캡처됩니다.

## 동작 원리

세션이 끝나면 에이전트의 Hook이 발동됩니다. WWT는 로그를 파싱하고, 코드를 추출하고, 대화를 **세 가지 덩어리 크기로 동시에** 쪼개고, 검색용 텍스트를 로컬에서 임베딩한 뒤(API 호출 없음) ChromaDB에 저장하고, 전체 원문은 SQLite에 보존합니다.

*"전에 그거 어떻게 했었지?"* 라고 물으면 — 어떤 에이전트든 MCP를 통해 `search_memory`를 호출합니다. WWT는 검색하고, 질문 의도에 맞춰 **한 번 더 순위를 조정**한 뒤, 간결한 미리보기를 반환하고, 필요한 덩어리만 `recall_chunk`로 원문 확장합니다. *무엇*을 했는지뿐 아니라, *왜* 그렇게 했는지까지 포함해서.

```
세션 종료 → Hook → 파싱 → 쪼개기(3가지 크기) → 임베딩 → ChromaDB + 원문 SQLite
질문         → MCP  → 검색 → 순위 재조정 → 미리보기 → 필요 시 원문 회수
```

### 세 가지 크기로 쪼개서 찾기 (v1.1)

같은 대화를 **세 가지 덩어리 크기**로 동시에 색인합니다. 질문에 맞는 크기가 자연스럽게 위로 올라오도록.

| 덩어리 크기 | 범위 | 잘 맞는 질문 |
|---|---|---|
| 짧은 조각 | 2턴 | "그때 에러 뭐였지?" 같은 사실 회수 |
| 중간 조각 | 2~6턴 (겹치며 이동) | "왜 X를 골랐지?" 같은 결정 맥락 |
| 세션 요약 | 대화 전체 (턴당 앞부분만) | "그날 뭐 했지?" 같은 개요 |

### 검색 결과 한 번 더 추려내기 (v1.1)

1차로 의미 유사도 + 키워드 매칭으로 후보를 뽑고, 질문 의도에 맞춰 순위를 재조정합니다 (추가 AI 호출 없음):

- **질문 유형에 맞는 덩어리가 먼저** — "왜" 질문엔 중간 조각, 코드 질문엔 짧은 조각, 개요 질문엔 세션 요약.
- **정확히 겹치는 단어**에 가점.
- **서로 겹치는 중복 결과**엔 감점.

## v1.1 업그레이드

v1.1은 세 가지 덩어리 크기 인덱싱과 검색 순위 재조정을 추가합니다. 저장 구조가 바뀌었으므로 업그레이드 후 한 번 재적재하세요:

```bash
wwt reset --force
wwt setup
```

> v1.0.x에서 올라오는 경우에도 이 재적재로 v1.0.12 원문 보존 구조까지 함께 반영됩니다.

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
| `search_remote_memory` | 집/회사 서버처럼 원격 게이트웨이에 쌓인 기억 조회 |
| `search_remote_decision` | 원격 게이트웨이에서 의사결정 이유 조회 |
| `search_remote_all` | 원격 게이트웨이 전체 범위 검색 |
| `recall_remote_chunk` | 원격 검색 결과의 `chunk_id` 원문 확장 |

`search_memory`는 **자동 라우팅**됩니다 — 프로젝트 필터가 충분한 결과를 못 내면, 자동으로 전체 프로젝트로 확장합니다 (Self-ROUTE, EMNLP 2024). 한 번의 호출, 재시도 없음.

## wwt를 사용하는 세 가지 방식

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

## 자주 쓰는 기억일수록 오래 남는다

시험공부에서 여러 번 꺼내본 내용이 오래 남는 것과 같은 원리입니다. WWT는 **실제로 원문을 다시 펼쳐본 대화**(`recall_chunk`로 확장한 것)를 더 천천히 잊습니다. 검색 미리보기만 훑은 건 "봤다"로 치지 않습니다 — 지나가는 검색까지 강화로 치면 잡음만 쌓이기 때문입니다.

검색 경로는 완전 읽기 전용이라, 여러 에이전트가 동시에 같은 DB를 검색해도 충돌이 없습니다.

최종 점수는 세 신호의 조합입니다:

```
최종 점수 = 의미 유사도 × (최근 사용 + 중요도)
```

오래된 핵심 결정이 최근 잡담을 이깁니다. 기억은 원래 그렇게 작동해야 합니다.

## 설치

```bash
pip install whatwasthat              # pip
uv tool install whatwasthat          # uv (권장)
```

그 다음 `wwt setup` 한 번. 머신에 이미 설치된 모든 에이전트(Claude Code, Gemini CLI, Codex CLI)에 MCP 서버를 등록하고 자동 캡처 Hook을 설치합니다. 여러 번 실행해도 안전합니다.

## Remote Mode

로컬 노트북과 집/회사 서버를 같이 쓰는 경우, 서버 쪽에 WWT 데이터를 모으고 각 클라이언트 에이전트는 원격 게이트웨이로 검색할 수 있습니다.

### 클라이언트 환경 변수

```bash
export WWT_REMOTE_BASE_URL="http://home-server:8000"
export WWT_REMOTE_API_TOKEN="change-me"
export WWT_REMOTE_TIMEOUT_SECONDS="30"
```

### 원격 업로드

기존 `remote-ingest`/`remote-ingest-all` CLI는 위 환경 변수를 읽어 세션을 원격 게이트웨이로 업로드합니다.

```bash
wwt remote-ingest --env home --date 2026-05-01
wwt remote-ingest --env home --date 2026-05-01 --source codex-cli --all-projects
wwt remote-ingest-all --env home --source claude-code
```

### 원격 검색 MCP 도구

- `search_remote_memory`: 현재 프로젝트 기준 원격 검색
- `search_remote_decision`: 원격 의사결정 검색
- `search_remote_all`: 원격 전체 검색
- `recall_remote_chunk`: 원격 chunk 원문 확장

로컬과 원격 도구 이름을 분리해, 에이전트가 어느 저장소를 조회하는지 명확히 유지합니다.

## Remote Gateway Server

게이트웨이는 Bearer 인증이 걸린 FastAPI 서버입니다. 같은 포맷의 ingest/search/recall API를 제공하고, 검색 응답은 모두 `{ "text": "..." }` 형태입니다.

### 직접 실행

```bash
export WWT_HOME=/var/lib/wwt
export WWT_REMOTE_API_TOKEN="change-me"
wwt-remote-api
```

### Docker Compose

예시 파일은 [docker/remote/Dockerfile](/Users/hyuk/PycharmProjects/whatwasthat/docker/remote/Dockerfile), [docker/remote/docker-compose.yml](/Users/hyuk/PycharmProjects/whatwasthat/docker/remote/docker-compose.yml), [docker/remote/.env.example](/Users/hyuk/PycharmProjects/whatwasthat/docker/remote/.env.example)에 있습니다.

```bash
cp docker/remote/.env.example docker/remote/.env
docker compose -f docker/remote/docker-compose.yml up -d --build
```

Tailscale 같은 overlay network 뒤에 두고 `WWT_REMOTE_BASE_URL`을 tailnet 주소로 맞추면, 집/회사 어디서든 같은 기억 저장소를 조회할 수 있습니다.

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
