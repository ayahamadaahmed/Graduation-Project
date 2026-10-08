from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)
from datetime import date

Language = Literal[
    "ar",
    "en",
    "mixed",
]


class KnowledgeDocument(BaseModel):

    document_id: str = Field(
        min_length=1,
        max_length=128,
    )

    tenant_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    )

    title: str = Field(
        min_length=1,
        max_length=200,
    )

    category: str = Field(
        min_length=1,
        max_length=64,
    )

    language: Language

    source: str = Field(
        min_length=1,
        max_length=500,
    )

    source_url: str | None = None

    source_type: str | None = None

    retrieved_at: date | None = None

    content: str = Field(
        min_length=1,
    )

    tags: list[str] = Field(
        default_factory=list,
    )


class KnowledgeChunk(BaseModel):

    chunk_id: str = Field(
        min_length=1,
        max_length=160,
    )

    document_id: str = Field(
        min_length=1,
        max_length=128,
    )

    tenant_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    )

    title: str = Field(
        min_length=1,
        max_length=200,
    )

    category: str = Field(
        min_length=1,
        max_length=64,
    )

    language: Language

    source: str = Field(
        min_length=1,
        max_length=500,
    )

    source_url: str | None = None

    source_type: str | None = None

    retrieved_at: date | None = None

    chunk_index: int = Field(
        ge=0,
    )

    content: str = Field(
        min_length=1,
    )

    tags: list[str] = Field(
        default_factory=list,
    )
