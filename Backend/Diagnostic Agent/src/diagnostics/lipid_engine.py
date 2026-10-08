from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.diagnostics.lab_types import (
    LabFinding,
    LabFlag,
    LabValue,
)


class LipidPattern(str, Enum):
    ALL_WITHIN_REFERENCE = "all_within_reference"

    TOTAL_CHOLESTEROL_ABOVE_REFERENCE = (
        "total_cholesterol_above_reference"
    )

    LDL_ABOVE_REFERENCE = (
        "ldl_above_reference"
    )

    HDL_BELOW_REFERENCE = (
        "hdl_below_reference"
    )

    TRIGLYCERIDES_ABOVE_REFERENCE = (
        "triglycerides_above_reference"
    )

    MULTIPLE_ABNORMAL = (
        "multiple_abnormal"
    )

    OUTSIDE_REFERENCE_RANGE = (
        "outside_reference_range"
    )

    PARTIAL_REFERENCE_DATA = (
        "partial_reference_data"
    )

    INSUFFICIENT_DATA = (
        "insufficient_data"
    )


@dataclass
class LipidAnalysisResult:
    findings: list[LabFinding] = field(
        default_factory=list
    )

    patterns: list[LipidPattern] = field(
        default_factory=list
    )

    @property
    def abnormal_findings(
        self,
    ) -> list[LabFinding]:

        return [
            finding
            for finding in self.findings
            if finding.flag
            in {
                LabFlag.LOW,
                LabFlag.HIGH,
            }
        ]


class LipidAnalyzer:
    """
    Descriptive lipid-profile analysis.

    Uses laboratory-provided
    reference ranges only.

    Does not diagnose cardiovascular disease.
    """

    SUPPORTED_FIELDS = {
        "total_cholesterol",
        "ldl",
        "hdl",
        "triglycerides",
        "vldl",

        "ldl_hdl_ratio",
        "total_cholesterol_hdl_ratio",
        "tg_hdl_ratio",
        "non_hdl_cholesterol",
    }

    DERIVED_FIELDS = {
        "ldl_hdl_ratio",
        "total_cholesterol_hdl_ratio",
        "tg_hdl_ratio",
        "non_hdl_cholesterol",
    }

    def analyze(
        self,
        values: list[LabValue],
    ) -> LipidAnalysisResult:

        supported = [
            value
            for value in values
            if value.name
            in self.SUPPORTED_FIELDS
        ]

        result = LipidAnalysisResult()

        if not supported:
            result.patterns.append(
                LipidPattern.INSUFFICIENT_DATA
            )

            return result

        for value in supported:
            result.findings.append(
                LabFinding(
                    name=value.name,
                    value=value.value,
                    unit=value.unit,
                    flag=value.flag(),
                    reference_min=value.reference_min,
                    reference_max=value.reference_max,
                )
            )

        result.patterns.extend(
            self._detect_patterns(
                result.findings
            )
        )

        return result

    def _detect_patterns(
        self,
        findings: list[LabFinding],
    ) -> list[LipidPattern]:

        # Primary lipid tests are allowed
        # to affect the final pattern.
        primary_findings = [
            finding
            for finding in findings
            if finding.name
            not in self.DERIVED_FIELDS
        ]

        # Ignore derived ratios when deciding
        # the main lipid pattern.
        abnormal = [
            finding
            for finding in primary_findings
            if finding.flag
            in {
                LabFlag.LOW,
                LabFlag.HIGH,
            }
        ]

        if not abnormal:
            if (
                primary_findings
                and all(
                    finding.flag
                    == LabFlag.NORMAL
                    for finding in primary_findings
                )
            ):
                return [
                    LipidPattern.ALL_WITHIN_REFERENCE
                ]

            has_normal = any(
                finding.flag == LabFlag.NORMAL
                for finding in primary_findings
            )

            has_unknown = any(
                finding.flag == LabFlag.UNKNOWN
                for finding in primary_findings
            )

            if has_normal and has_unknown:
                return [
                    LipidPattern.PARTIAL_REFERENCE_DATA
                ]

            return [
                LipidPattern.INSUFFICIENT_DATA
            ]

        if len(abnormal) > 1:
            return [
                LipidPattern.MULTIPLE_ABNORMAL
            ]

        finding = abnormal[0]

        if (
            finding.name == "total_cholesterol"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                LipidPattern.TOTAL_CHOLESTEROL_ABOVE_REFERENCE
            ]

        if (
            finding.name == "ldl"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                LipidPattern.LDL_ABOVE_REFERENCE
            ]

        if (
            finding.name == "hdl"
            and finding.flag == LabFlag.LOW
        ):
            return [
                LipidPattern.HDL_BELOW_REFERENCE
            ]

        if (
            finding.name == "triglycerides"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                LipidPattern.TRIGLYCERIDES_ABOVE_REFERENCE
            ]

        return [
            LipidPattern.OUTSIDE_REFERENCE_RANGE
        ]