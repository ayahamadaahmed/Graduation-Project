from __future__ import annotations

import logging
import os
import time

from functools import lru_cache

import numpy as np

from sentence_transformers import (
    SentenceTransformer,
)


logger = logging.getLogger("uvicorn.error")


MODEL_NAME = (
    "BAAI/bge-m3"
)

EMBEDDING_DEVICE = (
    os.getenv(
        "RAG_EMBEDDING_DEVICE",
        "cpu",
    )
    .strip()
    .lower()
)

QUERY_EMBEDDING_CACHE_SIZE = int(
    os.getenv(
        "RAG_QUERY_EMBEDDING_CACHE_SIZE",
        "256",
    )
)


@lru_cache(
    maxsize=1
)
def get_embedding_model() -> SentenceTransformer:

    return SentenceTransformer(
        MODEL_NAME,
        device=EMBEDDING_DEVICE,
    )


def _normalize_query_cache_key(
    text: str,
) -> str:

    return " ".join(
        text
        .strip()
        .casefold()
        .split()
    )


@lru_cache(
    maxsize=QUERY_EMBEDDING_CACHE_SIZE
)
def _embed_text_cached(
    normalized_text: str,
) -> np.ndarray:

    model = (
        get_embedding_model()
    )

    vector = (
        model.encode(
            normalized_text,
            normalize_embeddings=True,
        )
    )

    return vector


def embed_text(
    text: str,
) -> np.ndarray:

    normalized_text = (
        _normalize_query_cache_key(
            text
        )
    )

    if not normalized_text:
        raise ValueError(
            "text is required."
        )

    before = (
        _embed_text_cached
        .cache_info()
    )

    started = (
        time.perf_counter()
    )

    vector = (
        _embed_text_cached(
            normalized_text
        )
    )

    elapsed_ms = (
        time.perf_counter()
        - started
    ) * 1000

    after = (
        _embed_text_cached
        .cache_info()
    )

    cache_status = (
        "hit"
        if after.hits > before.hits
        else "miss"
    )

    logger.info(
        "rag_query_embedding_cache "
        "status=%s "
        "elapsed_ms=%.2f "
        "hits=%d "
        "misses=%d "
        "currsize=%d",
        cache_status,
        elapsed_ms,
        after.hits,
        after.misses,
        after.currsize,
    )

    return vector.copy()


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