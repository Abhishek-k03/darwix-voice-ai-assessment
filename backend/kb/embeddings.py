"""Multilingual embeddings (intfloat/multilingual-e5-small via fastembed ONNX, CPU). Covers EN/TL/ID."""

from __future__ import annotations

import functools
import os
from pathlib import Path

import numpy as np

MODEL = "intfloat/multilingual-e5-small"
DIM = 384
CACHE_DIR = Path(os.getenv("KB_MODEL_CACHE", Path(__file__).resolve().parents[2] / "data" / "models"))


@functools.lru_cache(maxsize=1)
def _model():
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    if MODEL not in {m["model"] for m in TextEmbedding.list_supported_models()}:
        TextEmbedding.add_custom_model(model=MODEL, pooling=PoolingType.MEAN, normalization=True,
                                       sources=ModelSource(hf=MODEL), dim=DIM, model_file="onnx/model.onnx")
    return TextEmbedding(MODEL, cache_dir=str(CACHE_DIR))


def embed_passages(texts: list[str]) -> np.ndarray:
    return np.array(list(_model().embed([f"passage: {t}" for t in texts], batch_size=32)), dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    return np.array(list(_model().embed([f"query: {text}"]))[0], dtype=np.float32)


def warmup() -> None:
    embed_query("warmup")
