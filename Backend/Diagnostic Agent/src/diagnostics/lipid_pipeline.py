from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    LabImageExtractor,
)

from src.diagnostics.lab_types import (
    LabValue,
)

from src.diagnostics.lipid_engine import (
    LipidAnalysisResult,
    LipidAnalyzer,
)

from src.diagnostics.lipid_normalizer import (
    NormalizedLipidValue,
    normalize_lipid_results,
)


@dataclass
class LipidPipelineResult:
    extracted_report: ExtractedLabReport

    normalized_results: list[
        NormalizedLipidValue
    ]

    analysis: LipidAnalysisResult

    skipped_unreadable: list[str] = field(
        default_factory=list
    )

    out_of_scope_tests: list[str] = field(
        default_factory=list
    )


class LipidPipeline:
    def __init__(
        self,
        extractor: LabImageExtractor,
        analyzer: LipidAnalyzer | None = None,
    ):
        self.extractor = extractor

        self.analyzer = (
            analyzer
            or LipidAnalyzer()
        )

    def run(
        self,
        image_path: str | Path,
    ) -> LipidPipelineResult:

        extracted = self.extractor.extract(
            image_path
        )

        normalized = normalize_lipid_results(
            extracted.results
        )

        normalized_raw_names = {
            item.raw_name
            for item in normalized
        }

        out_of_scope_tests = [
            item.raw_name
            for item in extracted.results
            if item.raw_name
            not in normalized_raw_names
        ]

        analyzer_values: list[LabValue] = []
        skipped_unreadable: list[str] = []

        for item in normalized:

            if item.value is None:
                skipped_unreadable.append(
                    item.raw_name
                )
                continue

            analyzer_values.append(
                LabValue(
                    name=item.name,
                    value=item.value,
                    unit=item.unit or "",
                    reference_min=(
                        item.reference_min
                    ),
                    reference_max=(
                        item.reference_max
                    ),
                )
            )

        analysis = self.analyzer.analyze(
            analyzer_values
        )

        return LipidPipelineResult(
            extracted_report=extracted,
            normalized_results=normalized,
            analysis=analysis,
            skipped_unreadable=(
                skipped_unreadable
            ),
            out_of_scope_tests=(
                out_of_scope_tests
            ),
        )