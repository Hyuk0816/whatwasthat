# APR 1st Week - Work Plan

## Friday (2026-04-03)

- 업무 목록
  - TOMT 프로젝트 architect.md 분석 및 아키텍처 파악
  - 구현 전 요구사항 확인 질문 정리
  - Phase 1 PoC 구현 계획 수립
  - Phase 1 PoC 전체 구현 완료 (parser → chunker → resolver → extractor → graph → vector → search → CLI)
  - 추출 품질 개선 작업 (파서 노이즈 제거, 프롬프트 튜닝)
  - Triplex 모델 시도 → 한국어 미지원으로 실패 → Qwen 3.5 복귀
  - ruff 린트 수정 + 38개 테스트 통과

### [결정] Phase 1 PoC 기술 스택
- 변경: Kuzu(그래프DB) + ChromaDB(벡터DB) + Ollama(Qwen 3.5 4B) 조합
- 이유: 임베디드 DB로 설치 부담 최소화, 로컬 LLM으로 프라이버시 보장
- 파일: src/whatwasthat/config.py

### [삽질] Triplex 모델 한국어 미지원
- 시도: KG 전문 모델 Triplex로 전환 (속도 18x 개선)
- 결과: 한국어 Unicode가 깨짐 — 엔티티명이 손상되어 0개 트리플 추출
- 해결: Qwen 3.5 4B로 복귀, Triplex 스타일 프롬프트(Entity Types + Predicates 명시) 적용
- 교훈: 소형 모델은 학습 데이터에 한국어가 충분한지 반드시 확인

## Saturday (2026-04-04)

- 업무 목록
  - Gemma 4 E4B 모델 교체 및 테스트 (17 → 26 트리플)
  - 프롬프트 Gemma 4 최적화 (Few-shot 예시, 한국어 유저 프롬프트)
  - 파서 시스템 블록 필터링 강화 (system-reminder 내용 제거)
  - 검색 엔진 트리플 필터링 개선 (쿼리 관련 엔티티 매칭)

### [결정] Gemma 4 E4B로 모델 교체
- 변경: Qwen 3.5 4B → Gemma 4 E4B (10GB, 140개 언어, 네이티브 JSON output)
- 이유: Qwen 대비 구조화 출력 준수율 높고 한국어 지원 양호
- 파일: src/whatwasthat/config.py

### [삽질] 트리플 추출 품질 한계
- 시도: Gemma 4 + 프롬프트 튜닝 + 파서 노이즈 제거
- 결과: 17개 트리플 (5청크 중 2개만 추출 성공), 핵심 기술 결정 누락
- 해결: 트리플 추출 방식 자체를 포기 → 청크 벡터화 방식으로 전환 결정
- 교훈: 소형 로컬 LLM으로 비정형 한국어 대화에서 구조화 추출은 비현실적

### [구조] 아키텍처 전환 설계: Triple → 청크 벡터화
- 변경: LLM 트리플 추출 제거, 청크 원문을 직접 벡터화하여 ChromaDB 저장
- 이유: 추출 품질 한계 + 속도(청크당 30~50초) + 사용자 배포 불가(10GB 모델)
- 영향: extractor/prompts/resolver/entity/graph 모듈 삭제, parser/chunker/vector/engine/cli 수정
- 파일: docs/plans/2026-04-05-vector-migration-design.md

## Sunday (2026-04-05)

- 업무 목록
  - 벡터 마이그레이션 설계 문서 작성 완료
  - Phase 1 구현 시작 예정
