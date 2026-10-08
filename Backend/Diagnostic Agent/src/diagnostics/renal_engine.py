from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.diagnostics.lab_types import (
    LabFinding,
    LabFlag,
    LabValue,
)


class RenalPattern(str, Enum):
    ALL_WITHIN_REFERENCE = "all_within_reference"

    CREATININE_ABOVE_REFERENCE = (
        "creatinine_above_reference"
    )

    CREATININE_BELOW_REFERENCE = (
        "creatinine_below_reference"
    )

    EGFR_BELOW_REFERENCE = (
        "egfr_below_reference"
    )

    BUN_ABOVE_REFERENCE = (
        "bun_above_reference"
    )

    UREA_ABOVE_REFERENCE = (
        "urea_above_reference"
    )

    MULTIPLE_ABNORMAL = (
        "multiple_abnormal"
    )

    INSUFFICIENT_DATA = (
        "insufficient_data"
    )


@dataclass
class RenalAnalysisResult:
    findings: list[LabFinding] = field(
        default_factory=list
    )

    patterns: list[RenalPattern] = field(
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


class RenalAnalyzer:
    """
    Descriptive kidney-function analysis.

    Uses only laboratory-provided
    reference ranges.

    Does not diagnose kidney disease.
    """

    SUPPORTED_FIELDS = {
        "creatinine",
        "egfr",
        "bun",
        "urea",
    }

    def analyze(
        self,
        values: list[LabValue],
    ) -> RenalAnalysisResult:

        supported = [
            value
            for value in values
            if value.name
            in self.SUPPORTED_FIELDS
        ]

        result = RenalAnalysisResult()

        if not supported:
            result.patterns.append(
                RenalPattern.INSUFFICIENT_DATA
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
    ) -> list[RenalPattern]:

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
                finding.flag
                == LabFlag.NORMAL
                for finding in findings
            ):
                return [
                    RenalPattern.ALL_WITHIN_REFERENCE
                ]

            return [
                RenalPattern.INSUFFICIENT_DATA
            ]

        if len(abnormal) > 1:
            return [
                RenalPattern.MULTIPLE_ABNORMAL
            ]

        finding = abnormal[0]

        if finding.name == "creatinine":
            if finding.flag == LabFlag.HIGH:
                return [
                    RenalPattern.CREATININE_ABOVE_REFERENCE
                ]

            return [
                RenalPattern.CREATININE_BELOW_REFERENCE
            ]

        if (
            finding.name == "egfr"
            and finding.flag == LabFlag.LOW
        ):
            return [
                RenalPattern.EGFR_BELOW_REFERENCE
            ]

        if (
            finding.name == "bun"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                RenalPattern.BUN_ABOVE_REFERENCE
            ]

        if (
            finding.name == "urea"
            and finding.flag == LabFlag.HIGH
        ):
            return [
                RenalPattern.UREA_ABOVE_REFERENCE
            ]

        return [
            RenalPattern.INSUFFICIENT_DATA
        ]