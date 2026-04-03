# Agent Context - WWT 프로젝트 구조 생성

## 작업 목적
whatwasthat (WWT) 프로젝트의 초기 디렉토리 구조와 스텁 파일을 생성한다.

## 프로젝트 개요
- AI 대화 기억 솔루션: LLM 대화를 Knowledge Graph로 변환
- CLI 명령어: `wwt`
- PyPI 패키지명: `whatwasthat`
- Python 3.12+, uv 패키지 매니저

## 기술 스택
- LLM: Qwen3.5 4B via Ollama (ollama 패키지)
- 임베딩: paraphrase-multilingual-MiniLM-L12-v2 (sentence-transformers)
- 그래프 DB: Kuzu (kuzu)
- 벡터 DB: ChromaDB (chromadb)
- CLI: typer
- 데이터 모델: pydantic
- MCP: mcp SDK
- 빌드: hatchling

## 코딩 컨벤션
- Python 3.12+ 문법 사용
- snake_case (변수, 함수), PascalCase (클래스)
- type hints 필수 (any 타입 사용 금지, 구체적 타입만)
- pydantic BaseModel로 데이터 모델 정의
- docstring: 한국어 허용, 간결하게
- 스텁 파일: 모듈 목적을 설명하는 docstring + 핵심 클래스/함수 시그니처만 (구현은 pass)

## 파이프라인 흐름
parser → chunker → resolver → extractor → entity → storage

## 핵심 데이터 모델 (models.py)
- Turn: role(str), content(str), timestamp(datetime | None)
- Chunk: id(str), session_id(str), turns(list[Turn]), raw_text(str)
- Triple: subject(str), subject_type(str), predicate(str), object(str), object_type(str), temporal(str | None)
- Entity: id(str), name(str), type(str), aliases(list[str])
- Session: id(str), source(str), created_at(datetime), summary(str)
- SearchResult: session_id(str), triples(list[Triple]), summary(str), score(float)
