from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class RadiologyPersistenceRequest(
    BaseModel
):

    schema_version: Literal[
        "1.0"
    ]

    attachment_id: str = Field(
        min_length=32,
        max_length=32,
    )

    modality: Literal[
        "chest_xray",
        "brain_mri",
        "kidney_ct",
    ]

    classification: str = Field(
        min_length=1,
        max_length=100,
    )

    probabilities: dict[
        str,
        Decimal,
    ] = Field(
        min_length=1,
    )

    confidence: Decimal = Field(
        ge=0,
        le=1,
    )

    inference_latency_ms: Decimal = Field(
        ge=0,
    )

    model_name: str = Field(
        min_length=1,
        max_length=150,
    )

    model_version: str = Field(
        min_length=1,
        max_length=100,
    )

    limitations: list[str] = Field(
        default_factory=list,
    )


class RadiologyPersistenceResponse(
    BaseModel
):

    attachment_id: str

    radiology_report_id: str

    status: Literal[
        "processed",
    ]