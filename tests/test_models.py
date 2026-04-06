from datetime import datetime

from whatwasthat.models import Chunk, SearchResult, SessionMeta


class TestSessionMeta:
    def test_create_session_meta(self):
        meta = SessionMeta(
            session_id="abc-123", project="whatwasthat",
            project_path="/Users/hyuk/PycharmProjects/whatwasthat",
            git_branch="main", started_at=datetime(2026, 4, 5),
        )
        assert meta.session_id == "abc-123"
        assert meta.project == "whatwasthat"
        assert meta.turn_count == 0


class TestChunkMetadata:
    def test_chunk_has_metadata_fields(self):
        chunk = Chunk(id="ch1", session_id="s1", turns=[], raw_text="test",
                      project="myproject", project_path="/path", git_branch="feature/x")
        assert chunk.project == "myproject"


class TestSearchResultChunks:
    def test_search_result_has_chunks(self):
        result = SearchResult(session_id="s1", chunks=[], summary="test",
                              score=0.8, project="myproject", git_branch="main")
        assert result.chunks == []
        assert result.project == "myproject"


class TestSourceField:
    def test_turn_has_source_field(self):
        from whatwasthat.models import Turn
        turn = Turn(role="user", content="hello", source="gemini-cli")
        assert turn.source == "gemini-cli"

    def test_turn_source_defaults_to_claude_code(self):
        from whatwasthat.models import Turn
        turn = Turn(role="user", content="hello")
        assert turn.source == "claude-code"

    def test_chunk_has_source_field(self):
        chunk = Chunk(id="abc", session_id="s1", turns=[], raw_text="test", source="gemini-cli")
        assert chunk.source == "gemini-cli"

    def test_session_meta_has_source_field(self):
        meta = SessionMeta(
            session_id="s1", project="proj", project_path="/p",
            git_branch="main", started_at=datetime.now(), source="gemini-cli"
        )
        assert meta.source == "gemini-cli"

    def test_search_result_has_source_field(self):
        result = SearchResult(session_id="s1", chunks=[], summary="", score=0.5, source="gemini-cli")
        assert result.source == "gemini-cli"
