from whatwasthat.pipeline.resolver import resolve_references
from whatwasthat.models import Chunk, Turn


def _make_chunk(conversations: list[tuple[str, str]]) -> Chunk:
    turns = [Turn(role=r, content=c) for r, c in conversations]
    raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in turns)
    return Chunk(id="c1", session_id="s1", turns=turns, raw_text=raw_text)


class TestResolveReferences:
    def test_no_pronouns_unchanged(self):
        chunk = _make_chunk([
            ("user", "FastAPI를 사용하자"),
            ("assistant", "FastAPI 좋습니다"),
        ])
        resolved = resolve_references(chunk)
        assert resolved.raw_text == chunk.raw_text

    def test_resolve_korean_pronoun_geugeol(self):
        chunk = _make_chunk([
            ("user", "FastAPI랑 Flask 중에 뭐가 좋아?"),
            ("assistant", "FastAPI가 async 지원이 좋습니다"),
            ("user", "그걸로 하자"),
        ])
        resolved = resolve_references(chunk)
        assert "FastAPI" in resolved.turns[2].content

    def test_resolve_korean_pronoun_geuge(self):
        chunk = _make_chunk([
            ("assistant", "GradientSHAP을 추천합니다"),
            ("user", "그게 뭐야?"),
        ])
        resolved = resolve_references(chunk)
        assert "GradientSHAP" in resolved.turns[1].content

    def test_raw_text_also_updated(self):
        chunk = _make_chunk([
            ("assistant", "PostgreSQL을 추천합니다"),
            ("user", "그걸로 하자"),
        ])
        resolved = resolve_references(chunk)
        assert "PostgreSQL" in resolved.raw_text
