"""트리플 추출용 프롬프트 템플릿 (Qwen + Triplex 스타일)."""

ENTITY_TYPES = [
    "Technology", "Framework", "Database", "Library", "Tool",
    "Language", "Model", "Feature", "Concept", "Service",
    "Problem", "Solution", "Reason", "Project", "Person",
]

PREDICATES = [
    "CHOSEN_OVER", "CHOSEN_BECAUSE", "REJECTED", "REJECTED_BECAUSE",
    "HAS_ADVANTAGE", "HAS_DISADVANTAGE", "USES", "DEPENDS_ON",
    "CAUSED", "SOLVED", "RENAMED_TO", "REPLACED_BY",
    "CONFIGURED_AS", "DECIDED_ON", "COMPARED_WITH",
]

SYSTEM_PROMPT = """/no_think
You extract knowledge graph triples from conversations.

Entity Types: {entity_types}
Predicates: {predicates}

Output JSON schema:
{{"triples":[{{"s":"subject","s_type":"EntityType","p":"PREDICATE","o":"object","o_type":"EntityType"}}]}}

Rules:
- Use EXACT names from the conversation (e.g. "FastAPI", "Kuzu", "ChromaDB")
- NEVER use vague descriptions like "optimal approach" or "Korean model"
- s_type and o_type must be from Entity Types list
- p must be from Predicates list
- Max 10 triples, focus on decisions and technical facts"""

USER_PROMPT = """Extract triples:
{chunk_text}"""
