from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.diagnostics.pathology_pipeline import (
    PathologyPipelineResult,
)


FindingFlagValue = Literal[
    "low",
    "normal",
    "high",
    "unknown",
]


class PathologyFindingSchema(BaseModel):
    name: str
    value: float
    unit: str

    flag: FindingFlagValue

    reference_min: float | None = None
    reference_max: float | None = None


class PathologyResponseSchema(BaseModel):
    schema_version: str = "1.0"

    document_type: str | None = None

    detected_panels: list[str]

    abnormal_findings: list[
        PathologyFindingSchema
    ]

    normal_findings: list[
        PathologyFindingSchema
    ]

    unknown_findings: list[
        PathologyFindingSchema
    ]

    skipped_unreadable: list[str]

    unmapped_tests: list[str]


def _finding_to_schema(
    finding,
) -> PathologyFindingSchema:

    return PathologyFindingSchema(
        name=finding.name,
        value=finding.value,
        unit=finding.unit,
        flag=finding.flag.value,
        reference_min=(
            finding.reference_min
        ),
        reference_max=(
            finding.reference_max
        ),
    )


def pathology_result_to_schema(
    result: PathologyPipelineResult,
) -> PathologyResponseSchema:

    assessment = result.assessment

    return PathologyResponseSchema(
        document_type=(
            result.extracted_report.document_type
        ),

        detected_panels=list(
            assessment.detected_panels
        ),

        abnormal_findings=[
            _finding_to_schema(finding)
            for finding
            in assessment.abnormal_findings
        ],

        normal_findings=[
            _finding_to_schema(finding)
            for finding
            in assessment.normal_findings
        ],

        unknown_findings=[
            _finding_to_schema(finding)
            for finding
            in assessment.unknown_findings
        ],

        skipped_unreadable=list(
            assessment.skipped_unreadable
        ),

        unmapped_tests=list(
            assessment.unmapped_tests
        ),
    )