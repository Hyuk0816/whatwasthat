# Agent Context - WWT Phase 1 PoC 구현

## 작업 목적
whatwasthat (WWT) Phase 1 PoC 구현. 대화 로그 1개로 전체 파이프라인 관통.

## 프로젝트 개요
- AI 대화 기억 솔루션: LLM 대화를 Knowledge Graph로 변환
- CLI 명령어: `wwt`, PyPI: `whatwasthat`
- Python 3.12+, uv 패키지 매니저

## 기술 스택
- LLM: Qwen3.5 4B via Ollama (`ollama` 패키지)
- 임베딩: paraphrase-multilingual-MiniLM-L12-v2 (`sentence-transformers`)
- 그래프 DB: Kuzu (`kuzu`)
- 벡터 DB: ChromaDB (`chromadb`)
- CLI: `typer`
- 데이터 모델: `pydantic` BaseModel
- 빌드: `hatchling`

## 코딩 컨벤션
- Python 3.12+ 문법
- snake_case (변수/함수), PascalCase (클래스)
- type hints 필수 (`any` 타입 사용 금지)
- pydantic BaseModel로 데이터 모델
- TDD: 테스트 먼저 작성 → 실패 확인 → 구현 → 통과 확인
- 테스트 실행: `cd /Users/hyuk/PycharmProjects/whatwasthat && uv run pytest <path> -v`
- **git commit 하지 마세요** — 컨트롤러가 일괄 커밋합니다

## 핵심 데이터 모델 (src/whatwasthat/models.py — 이미 존재, 수정 금지)
- Turn: role(str), content(str), timestamp(datetime | None)
- Chunk: id(str), session_id(str), turns(list[Turn]), raw_text(str), timestamp(datetime | None)
- Triple: subject(str), subject_type(str), predicate(str), object(str), object_type(str), temporal(str | None), confidence(float)
- Entity: id(str), name(str), type(str), aliases(list[str]), created_at(datetime), updated_at(datetime)
- Session: id(str), source(str), created_at(datetime), summary(str)
- SearchResult: session_id(str), triples(list[Triple]), summary(str), score(float)

## 현재 완료된 Task
- Task 1: Parser (parser.py) ✅ — JSONL → Turn 리스트 변환

## 병렬 실행 주의사항
- 각 에이전트는 자기 파일만 수정 (다른 에이전트 파일 수정 금지)
- models.py, config.py, conftest.py 수정 금지
- git commit 하지 마세요
