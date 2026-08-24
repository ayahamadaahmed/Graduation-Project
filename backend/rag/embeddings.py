from __future__ import annotations

from functools import lru_cache

import numpy as np

from sentence_transformers import (
    SentenceTransformer,
)


MODEL_NAME = (
    "BAAI/bge-m3"
)


@lru_cache(
    maxsize=1
)
def get_embedding_model() -> SentenceTransformer:

    return SentenceTransformer(
        MODEL_NAME
    )


def embed_text(
    text: str,
) -> np.ndarray:

    model = (
        get_embedding_model()
    )

    vector = (
        model.encode(
            text,
            normalize_embeddings=True,
        )
    )

    return vector


def embed_texts(
    texts: list[str],
) -> np.ndarray:

    model = (
        get_embedding_model()
    )

    vectors = (
        model.encode(
            texts,
            normalize_embeddings=True,
        )
    )

    return vectors