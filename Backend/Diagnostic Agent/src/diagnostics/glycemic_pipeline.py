from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.diagnostics.glycemic_engine import (
    GlycemicAnalysisResult,
    GlycemicAnalyzer,
)

from src.diagnostics.glycemic_normalizer import (
    NormalizedGlycemicValue,
    normalize_glycemic_results,
)

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    LabImageExtractor,
)

from src.diagnostics.lab_types import (
    LabValue,
)


@dataclass
class GlycemicPipelineResult:
    extracted_report: ExtractedLabReport

    normalized_results: list[
        NormalizedGlycemicValue
    ]

    analysis: GlycemicAnalysisResult

    skipped_unreadable: list[str] = field(
        default_factory=list
    )

    out_of_scope_tests: list[str] = field(
        default_factory=list
    )


class GlycemicPipeline:
    def __init__(
        self,
        extractor: LabImageExtractor,
        analyzer: GlycemicAnalyzer | None = None,
    ):
        self.extractor = extractor
        self.analyzer = (
            analyzer
            or GlycemicAnalyzer()
        )

    def run(
        self,
        image_path: str | Path,
    ) -> GlycemicPipelineResult:

        extracted = self.extractor.extract(
            image_path
        )

        normalized = normalize_glycemic_results(
            extracted.results
        )

        normalized_raw_names = {
            result.raw_name
            for result in normalized
        }

        out_of_scope_tests = [
            result.raw_name
            for result in extracted.results
            if result.raw_name
            not in normalized_raw_names
        ]

        analyzer_values: list[LabValue] = []
        skipped_unreadable: list[str] = []

        for result in normalized:
            if result.value is None:
                skipped_unreadable.append(
                    result.raw_name
                )
                continue

            analyzer_values.append(
                LabValue(
                    name=result.name,
                    value=result.value,
                    unit=result.unit or "",
                    reference_min=(
                        result.reference_min
                    ),
                    reference_max=(
                        result.reference_max
                    ),
                )
            )

        analysis = self.analyzer.analyze(
            analyzer_values
        )

        return GlycemicPipelineResult(
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