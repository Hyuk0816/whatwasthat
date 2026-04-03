# WWT 프로젝트 구조 설계

**날짜**: 2026-04-03
**상태**: 확정

## 개요

whatwasthat (WWT) 프로젝트의 디렉토리 레이아웃과 모듈 구성을 정의한다.

## 디렉토리 구조

```
whatwasthat/
├── pyproject.toml
├── src/
│   └── whatwasthat/
│       ├── __init__.py
│       ├── config.py
│       ├── models.py
│       ├── cli/
│       │   ├── __init__.py
│       │   └── app.py
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── parser.py
│       │   ├── chunker.py
│       │   ├── resolver.py
│       │   ├── extractor.py
│       │   └── entity.py
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── graph.py
│       │   └── vector.py
│       ├── search/
│       │   ├── __init__.py
│       │   └── engine.py
│       └── server/
│           ├── __init__.py
│           └── mcp.py
├── tests/
│   ├── conftest.py
│   ├── test_pipeline/
│   ├── test_storage/
│   ├── test_search/
│   └── test_server/
└── docs/
    └── plans/
```

## 패키지 설계 원칙

### 도메인별 분리
- **pipeline/**: 대화 로그 → 트리플 변환 파이프라인
- **storage/**: Kuzu + ChromaDB 영속화 계층
- **search/**: 하이브리드 검색 엔진
- **server/**: MCP 서버 (외부 인터페이스)
- **cli/**: typer 기반 CLI

### 공통 모듈
- **config.py**: 경로, 모델명, 전역 설정
- **models.py**: pydantic 데이터 모델 (Turn, Chunk, Triple, Entity, Session, SearchResult)

### 의존성 방향
```
cli → pipeline → storage
       ↓           ↑
     models ←── search
       ↑
     server → search → storage
```

- models.py는 모든 패키지에서 참조 (순환 의존 없음)
- pipeline은 storage에 직접 의존하지 않음 (cli/app.py에서 조합)
- search는 storage를 주입받음 (DI 패턴)

## 기술 스택

| 항목 | 선택 | 버전 |
|------|------|------|
| Python | 3.12+ | - |
| 패키지 매니저 | uv | - |
| 빌드 백엔드 | hatchling | - |
| CLI | typer | >=0.15 |
| 그래프 DB | kuzu | >=0.9 |
| 벡터 DB | chromadb | >=0.6 |
| LLM | ollama | >=0.4 |
| 임베딩 | sentence-transformers | >=3.3 |
| 데이터 모델 | pydantic | >=2.10 |
| MCP | mcp | >=1.0 |
| 테스트 | pytest | >=8.0 |
| 린터 | ruff | >=0.9 |

## Phase 1 PoC 범위

파이프라인 관통 테스트:
1. Claude Code JSONL 1개 파싱 (parser.py)
2. 주제 기반 청킹 (chunker.py)
3. 대명사 해소 (resolver.py)
4. 트리플 추출 (extractor.py)
5. Kuzu + ChromaDB 저장 (storage/)
6. CLI 검색 확인 (cli/ + search/)

MCP 서버는 Phase 2에서 구현.
