"""ONNX Runtime 기반 임베딩 함수 — torch 의존성 제거."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from whatwasthat.config import EMBEDDING_MODEL

_SESSION = None
_TOKENIZER = None


def _ensure_model() -> tuple:
    """ONNX 모델 + 토크나이저 lazy 로딩."""
    global _SESSION, _TOKENIZER  # noqa: PLW0603
    if _SESSION is not None:
        return _SESSION, _TOKENIZER

    from huggingface_hub import snapshot_download
    from onnxruntime import InferenceSession
    from tokenizers import Tokenizer

    # HuggingFace에서 ONNX 모델 다운로드 (캐시됨)
    model_dir = Path(snapshot_download(
        EMBEDDING_MODEL,
        allow_patterns=["onnx/*", "tokenizer.json", "tokenizer_config.json"],
    ))

    onnx_path = model_dir / "onnx" / "model.onnx"
    if not onnx_path.exists():
        # fallback: model.onnx가 루트에 있을 수도 있음
        onnx_path = model_dir / "model.onnx"

    if not onnx_path.exists():
        raise FileNotFoundError(
            f"ONNX 모델을 찾을 수 없습니다: {model_dir}. "
            "intfloat/multilingual-e5-small에 ONNX 모델이 포함되어 있는지 확인하세요."
        )

    _SESSION = InferenceSession(
        str(onnx_path),
        providers=["CPUExecutionProvider"],
    )

    tokenizer_path = model_dir / "tokenizer.json"
    _TOKENIZER = Tokenizer.from_file(str(tokenizer_path))
    _TOKENIZER.enable_truncation(max_length=512)
    _TOKENIZER.enable_padding(pad_id=0, pad_token="[PAD]", length=512)

    return _SESSION, _TOKENIZER


class OnnxEmbeddingFunction(EmbeddingFunction[Documents]):
    """ChromaDB 호환 ONNX 임베딩 함수."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def name() -> str:
        """ChromaDB 호환 이름 — 기존 컬렉션과의 충돌 방지."""
        return "sentence_transformer"

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []

        session, tokenizer = _ensure_model()

        # e5 모델은 "query: " 접두사 필요
        prefixed = [f"query: {text}" for text in input]
        encoded = tokenizer.encode_batch(prefixed)

        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)

        outputs = session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )

        # Mean pooling (attention mask 적용)
        token_embeddings = outputs[0]  # (batch, seq_len, hidden_dim)
        mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
        summed = np.sum(token_embeddings * mask_expanded, axis=1)
        counts = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        embeddings = summed / counts

        # L2 정규화
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / np.clip(norms, a_min=1e-9, a_max=None)

        return normalized.tolist()
