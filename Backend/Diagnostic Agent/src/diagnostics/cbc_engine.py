from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from src.diagnostics.lab_types import (
    LabFinding,
    LabFlag,
    LabValue,
)

class CBCPattern(str, Enum):
    LOW_HEMOGLOBIN_MICROCYTIC = (
        "low_hemoglobin_microcytic_pattern"
    )

    LOW_HEMOGLOBIN_NORMOCYTIC = (
        "low_hemoglobin_normocytic_pattern"
    )

    LOW_HEMOGLOBIN_MACROCYTIC = (
        "low_hemoglobin_macrocytic_pattern"
    )

    HEMOGLOBIN_WITHIN_REFERENCE = (
        "hemoglobin_within_reference"
    )

    HEMOGLOBIN_ABOVE_REFERENCE = (
        "hemoglobin_above_reference"
    )

    INSUFFICIENT_DATA = (
        "insufficient_data"
    )

@dataclass
class CBCAnalysisResult:
    findings: list[LabFinding] = field(default_factory=list)
    patterns: list[CBCPattern] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    @property
    def abnormal_findings(self) -> list[LabFinding]:
        return [
            finding
            for finding in self.findings
            if finding.flag in {LabFlag.LOW, LabFlag.HIGH}
        ]


class CBCAnalyzer:
    """
    Deterministic CBC interpretation engine.

    Important:
    - Uses the laboratory-provided reference range.
    - Does not diagnose a disease.
    - Does not infer iron deficiency or thalassemia.
    - Produces descriptive CBC patterns only.
    """

    CORE_FIELDS = {
        "hemoglobin",
        "mcv",
        "wbc",
        "platelets",
    }

    def analyze(
        self,
        values: list[LabValue],
    ) -> CBCAnalysisResult:

        by_name = {
            item.name.strip().lower(): item
            for item in values
        }

        result = CBCAnalysisResult()

        for name in self.CORE_FIELDS:
            if name not in by_name:
                result.missing_fields.append(name)

        for item in values:
            result.findings.append(
                LabFinding(
                    name=item.name,
                    value=item.value,
                    unit=item.unit,
                    flag=item.flag(),
                    reference_min=item.reference_min,
                    reference_max=item.reference_max,
                )
            )

        result.patterns.extend(
            self._detect_red_cell_pattern(by_name)
        )

        return result
    
    def _detect_red_cell_pattern(
        self,
        values: dict[str, LabValue],
    ) -> list[CBCPattern]:

        hemoglobin = values.get("hemoglobin")
        mcv = values.get("mcv")

        if hemoglobin is None:
            return [
                CBCPattern.INSUFFICIENT_DATA
            ]

        hb_flag = hemoglobin.flag()

        if hb_flag == LabFlag.UNKNOWN:
            return [
                CBCPattern.INSUFFICIENT_DATA
            ]

        if hb_flag == LabFlag.NORMAL:
            return [
                CBCPattern.HEMOGLOBIN_WITHIN_REFERENCE
            ]

        if hb_flag == LabFlag.HIGH:
            return [
                CBCPattern.HEMOGLOBIN_ABOVE_REFERENCE
            ]

        # From here hemoglobin is LOW.
        # MCV is required to describe the
        # red-cell size pattern.
        if mcv is None:
            return [
                CBCPattern.INSUFFICIENT_DATA
            ]

        mcv_flag = mcv.flag()

        if mcv_flag == LabFlag.LOW:
            return [
                CBCPattern.LOW_HEMOGLOBIN_MICROCYTIC
            ]

        if mcv_flag == LabFlag.NORMAL:
            return [
                CBCPattern.LOW_HEMOGLOBIN_NORMOCYTIC
            ]

        if mcv_flag == LabFlag.HIGH:
            return [
                CBCPattern.LOW_HEMOGLOBIN_MACROCYTIC
            ]

        return [
            CBCPattern.INSUFFICIENT_DATA
        ]