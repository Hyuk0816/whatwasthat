# Agent Context — Vector Migration

## 작업 목적
WWT 프로젝트를 Triple 추출 방식에서 청크 벡터화 방식으로 전환 중.
설계 문서: docs/plans/2026-04-05-vector-migration-design.md
구현 계획: docs/plans/2026-04-05-vector-migration-impl.md

## 프로젝트 개요
- AI 대화 기억 검색: LLM 대화 로그를 벡터화하여 시맨틱 검색
- CLI: `wwt`, PyPI: `whatwasthat`
- Python 3.12+, uv 패키지 매니저

## 코딩 컨벤션
- Python 3.12+ 문법
- snake_case (변수/함수), PascalCase (클래스)
- type hints 필수 (`any` 타입 사용 금지, 구체적 타입 사용)
- pydantic BaseModel로 데이터 모델
- TDD: 테스트 먼저 작성 → 실패 확인 → 구현 → 통과 확인
- 테스트 실행: `cd /Users/hyuk/PycharmProjects/whatwasthat && uv run pytest <path> -v`
- ruff lint: line-length=100, target py312
- **git commit 하지 마세요** — 컨트롤러가 일괄 커밋합니다

## 핵심 변경 방향
- Ollama LLM 호출 제거 (트리플 추출 삭제)
- Kuzu 그래프 DB 제거
- ChromaDB에 청크 원문 + 메타데이터 직접 저장
- 검색: 벡터 시맨틱 → 세션별 그루핑 → 청크 원문 반환
