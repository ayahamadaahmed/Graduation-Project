from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.diagnostics.lab_types import (
    LabFinding,
    LabFlag,
    LabValue,
)


class GlycemicPattern(str, Enum):
    ALL_WITHIN_REFERENCE = "all_within_reference"
    GLUCOSE_ABOVE_REFERENCE = "glucose_above_reference"
    GLUCOSE_BELOW_REFERENCE = "glucose_below_reference"
    HBA1C_ABOVE_REFERENCE = "hba1c_above_reference"
    HBA1C_BELOW_REFERENCE = "hba1c_below_reference"
    MULTIPLE_ABNORMAL = "multiple_abnormal"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class GlycemicAnalysisResult:
    findings: list[LabFinding] = field(
        default_factory=list
    )

    patterns: list[GlycemicPattern] = field(
        default_factory=list
    )

    missing_fields: list[str] = field(
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


class GlycemicAnalyzer:
    """
    Descriptive glucose/HbA1c analysis.

    Important:
    - Uses laboratory-provided reference ranges.
    - Does not diagnose diabetes.
    - Does not invent missing ranges.
    - Missing data remains missing/unknown.
    """

    SUPPORTED_FIELDS = {
        "fasting_glucose",
        "random_glucose",
        "glucose",
        "hba1c",
    }

    def analyze(
        self,
        values: list[LabValue],
    ) -> GlycemicAnalysisResult:

        supported_values = [
            value
            for value in values
            if value.name in self.SUPPORTED_FIELDS
        ]

        result = GlycemicAnalysisResult()

        if not supported_values:
            result.patterns.append(
                GlycemicPattern.INSUFFICIENT_DATA
            )

            result.missing_fields.extend(
                [
                    "glucose",
                    "hba1c",
                ]
            )

            return result

        for value in supported_values:
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
    ) -> list[GlycemicPattern]:

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
                    GlycemicPattern.ALL_WITHIN_REFERENCE
                ]

            return [
                GlycemicPattern.INSUFFICIENT_DATA
            ]

        if len(abnormal) > 1:
            return [
                GlycemicPattern.MULTIPLE_ABNORMAL
            ]

        finding = abnormal[0]

        if (
            finding.name
            in {
                "glucose",
                "fasting_glucose",
                "random_glucose",
            }
        ):
            if finding.flag == LabFlag.HIGH:
                return [
                    GlycemicPattern.GLUCOSE_ABOVE_REFERENCE
                ]

            return [
                GlycemicPattern.GLUCOSE_BELOW_REFERENCE
            ]

        if finding.name == "hba1c":
            if finding.flag == LabFlag.HIGH:
                return [
                    GlycemicPattern.HBA1C_ABOVE_REFERENCE
                ]

            return [
                GlycemicPattern.HBA1C_BELOW_REFERENCE
            ]

        return [
            GlycemicPattern.INSUFFICIENT_DATA
        ]