"""트리플 추출용 프롬프트 템플릿."""

EXTRACTION_PROMPT = """아래 대화에서 사실, 결정, 관계를 추출하세요.
반드시 JSON으로만 응답하세요. 마크다운 코드블록 없이 순수 JSON만 출력하세요.

{{"triples": [
  {{"s": "주어", "s_type": "타입", "p": "관계", "o": "목적어", "o_type": "타입", "temporal": "decided|rejected|ongoing|null"}}
]}}

### 예시 1
입력: "[user]: FastAPI 대신 Flask 쓰자\\n[assistant]: FastAPI가 async 좋으니 유지하자\\n[user]: 그래 FastAPI로"
출력: {{"triples": [
  {{"s":"FastAPI","s_type":"Framework","p":"CHOSEN_OVER","o":"Flask","o_type":"Framework","temporal":"decided"}},
  {{"s":"FastAPI","s_type":"Framework","p":"HAS_ADVANTAGE","o":"async 지원","o_type":"Feature","temporal":null}}
]}}

### 예시 2
입력: "[user]: 이 에러 뭐 때문이지?\\n[assistant]: pip 버전 문제입니다\\n[user]: 업그레이드하니 해결됐다"
출력: {{"triples": [
  {{"s":"pip 구버전","s_type":"Problem","p":"CAUSED","o":"에러","o_type":"Issue","temporal":null}},
  {{"s":"pip upgrade","s_type":"Solution","p":"SOLVED","o":"에러","o_type":"Issue","temporal":"decided"}}
]}}

### 실제 입력
{chunk_text}
"""
