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
