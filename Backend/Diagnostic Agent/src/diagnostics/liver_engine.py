from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.diagnostics.lab_types import (
    LabFinding,
    LabFlag,
    LabValue,
)


class LiverPattern(str, Enum):
    ALL_WITHIN_REFERENCE = "all_within_reference"

    ALT_ABOVE_REFERENCE = (
        "alt_above_reference"
    )

    AST_ABOVE_REFERENCE = (
        "ast_above_reference"
    )

    ALP_ABOVE_REFERENCE = (
        "alp_above_reference"
    )

    BILIRUBIN_ABOVE_REFERENCE = (
        "bilirubin_above_reference"
    )

    ALBUMIN_BELOW_REFERENCE = (
        "albumin_below_reference"
    )

    MULTIPLE_ABNORMAL = (
        "multiple_abnormal"
    )

    INSUFFICIENT_DATA = (
        "insufficient_data"
    )
    OUTSIDE_REFERENCE_RANGE = (
        "outside_reference_range"
    )
    PARTIAL_REFERENCE_DATA = (
        "partial_reference_data"
    )


@dataclass
class LiverAnalysisResult:
    findings: list[LabFinding] = field(
        default_factory=list
    )

    patterns: list[LiverPattern] = field(
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


class LiverAnalyzer:
    """
    Descriptive liver-function analysis.

    Uses laboratory-provided
    reference ranges only.

    Does not diagnose liver disease.
    """

    SUPPORTED_FIELDS = {
        "alt",
        "ast",
        "alp",

        "total_bilirubin",
        "direct_bilirubin",
        "indirect_bilirubin",

        "total_protein",
        "albumin",
        "globulin",
        "ag_ratio",
    }

    def analyze(
        self,
        values: list[LabValue],
    ) -> LiverAnalysisResult:

        supported = [
            value
            for value in values
            if value.name
            in self.SUPPORTED_FIELDS
        ]

        result = LiverAnalysisResult()

        if not supported:
            result.patterns.append(
                LiverPattern.INSUFFICIENT_DATA
            )

            return result

        for value in supported:
            result.findings.append(
                LabFinding(
                    name=value.name,
                    value=value.value,
                    unit=value.unit,
                    flag=value.flag(),
                    reference_min=(
                        value.reference_min
                    ),
                    reference_max=(
                        value.reference_max
                    ),
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
    ) -> list[LiverPattern]:

        abnormal = [
            finding
            for finding in findings
            if finding.flag
            in {
                LabFlag.LOW,
                LabFlag.HIGH,
            }
        ]

        if not abnormal:
            if all(
                finding.flag == LabFlag.NORMAL
                for finding in findings
            ):
                return [
                    LiverPattern.ALL_WITHIN_REFERENCE
                ]

            has_normal = any(
                finding.flag == LabFlag.NORMAL
                for finding in findings
            )

            has_unknown = any(
                finding.flag == LabFlag.UNKNOWN
                for finding in findings
            )

            if has_normal and has_unknown:
                return [
                    LiverPattern.PARTIAL_REFERENCE_DATA
                ]

            return [
                LiverPattern.INSUFFICIENT_DATA
            ]

        if len(abnormal) > 1:
            return [
                LiverPattern.MULTIPLE_ABNORMAL
            ]

        finding = abnormal[0]

        if (
            finding.name == "alt"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                LiverPattern.ALT_ABOVE_REFERENCE
            ]

        if (
            finding.name == "ast"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                LiverPattern.AST_ABOVE_REFERENCE
            ]

        if (
            finding.name == "alp"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                LiverPattern.ALP_ABOVE_REFERENCE
            ]

        if (
            finding.name == "total_bilirubin"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                LiverPattern.BILIRUBIN_ABOVE_REFERENCE
            ]

        if (
            finding.name == "albumin"
            and finding.flag == LabFlag.LOW
        ):
            return [
                LiverPattern.ALBUMIN_BELOW_REFERENCE
            ]

        return [
            LiverPattern.OUTSIDE_REFERENCE_RANGE
        ]