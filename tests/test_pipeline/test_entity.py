from whatwasthat.pipeline.entity import resolve_entity
from whatwasthat.models import Entity


class TestResolveEntity:
    def test_exact_match(self):
        existing = [
            Entity(id="e1", name="FastAPI", type="Framework"),
        ]
        result = resolve_entity("FastAPI", existing)
        assert result is not None
        assert result.id == "e1"

    def test_normalized_match_case_insensitive(self):
        existing = [
            Entity(id="e1", name="FastAPI", type="Framework"),
        ]
        result = resolve_entity("fastapi", existing)
        assert result is not None
        assert result.id == "e1"

    def test_normalized_match_whitespace(self):
        existing = [
            Entity(id="e1", name="Gradient SHAP", type="Technology"),
        ]
        result = resolve_entity("GradientSHAP", existing)
        assert result is not None
        assert result.id == "e1"

    def test_no_match_returns_none(self):
        existing = [
            Entity(id="e1", name="FastAPI", type="Framework"),
        ]
        result = resolve_entity("PostgreSQL", existing)
        assert result is None

    def test_empty_existing(self):
        result = resolve_entity("FastAPI", [])
        assert result is None
