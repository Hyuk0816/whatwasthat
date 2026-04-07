"""ONNX 임베딩 함수 테스트."""
import pytest

from whatwasthat.embedding import OnnxEmbeddingFunction


class TestOnnxEmbedding:
    def test_embed_returns_correct_dimension(self):
        ef = OnnxEmbeddingFunction()
        result = ef(["hello world"])
        assert len(result) == 1
        assert len(result[0]) == 384  # e5-small 차원

    def test_embed_multiple_texts(self):
        ef = OnnxEmbeddingFunction()
        result = ef(["hello", "world"])
        assert len(result) == 2
        assert all(len(v) == 384 for v in result)

    def test_embed_korean(self):
        ef = OnnxEmbeddingFunction()
        result = ef(["한국어 임베딩 테스트"])
        assert len(result[0]) == 384

    def test_callable_interface(self):
        """ChromaDB EmbeddingFunction 인터페이스 준수."""
        ef = OnnxEmbeddingFunction()
        assert callable(ef)

    def test_embed_empty_list(self):
        """빈 리스트 → ChromaDB 래퍼가 ValueError 발생."""
        ef = OnnxEmbeddingFunction()
        # ChromaDB EmbeddingFunction 래퍼가 빈 결과를 거부함
        with pytest.raises((ValueError, AssertionError)):
            ef([])
