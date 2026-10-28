from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class PathologyResultPersistenceItem(
    BaseModel
):

    result_index: int = Field(
        ge=0,
    )

    panel: Literal[
        "cbc",
        "glycemic",
        "renal",
        "liver",
        "lipid",
        "additional_labs",
    ] | None = None

    raw_name: str = Field(
        min_length=1,
        max_length=200,
    )

    canonical_name: str | None = Field(
        default=None,
        max_length=100,
    )

    value: Decimal | None = None

    unit: str | None = Field(
        default=None,
        max_length=50,
    )

    reference_min: Decimal | None = None
    reference_max: Decimal | None = None

    reference_text: str | None = Field(
        default=None,
        max_length=200,
    )

    flag: Literal[
        "low",
        "normal",
        "high",
        "unknown",
    ]

    mapping_status: Literal[
        "mapped",
        "unmapped",
        "unreadable",
    ]


class PathologyPersistenceRequest(
    BaseModel
):

    schema_version: Literal["1.0"]

    attachment_id: str = Field(
        min_length=32,
        max_length=32,
    )

    document_type: str | None = Field(
        default=None,
        max_length=50,
    )

    unreadable_fields: list[str] = Field(
        default_factory=list,
    )

    results: list[
        PathologyResultPersistenceItem
    ] = Field(
        min_length=1,
    )


class PathologyPersistenceResponse(
    BaseModel
):

    attachment_id: str

    lab_report_id: str

    status: Literal[
        "processed",
    ]

    result_count: int = Field(
        ge=1,
    )
