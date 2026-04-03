"""트리플 추출용 프롬프트 템플릿 (Triplex 모델용)."""

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

TRIPLEX_PROMPT = """**Entity Types:** {entity_types}
**Predicates:** {predicates}
**Text:** {chunk_text}"""
