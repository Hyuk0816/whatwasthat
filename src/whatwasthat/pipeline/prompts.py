"""트리플 추출용 프롬프트 템플릿."""

SYSTEM_PROMPT = """/no_think
You extract knowledge triples from conversations. Always respond with this exact JSON schema:
{"triples":[{"s":"subject","s_type":"type","p":"PREDICATE","o":"object","o_type":"type","temporal":"decided|rejected|ongoing|null"}]}

Rules:
- Only use keys: s, s_type, p, o, o_type, temporal
- No other keys or formats allowed
- temporal: "decided" for final choices, "rejected" for discarded options, null otherwise
- Keep triples concise, max 10 per chunk

Example input: "[user]: Use Flask\\n[assistant]: FastAPI is better for async\\n[user]: OK FastAPI"
Example output: {"triples":[{"s":"FastAPI","s_type":"Framework","p":"CHOSEN_OVER","o":"Flask","o_type":"Framework","temporal":"decided"}]}"""

USER_PROMPT = """Extract triples from this conversation:
{chunk_text}"""
