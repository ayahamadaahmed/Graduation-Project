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

from src.diagnostics.liver_engine import (
    LiverAnalysisResult,
    LiverAnalyzer,
)

from src.diagnostics.liver_normalizer import (
    NormalizedLiverValue,
    normalize_liver_results,
)


@dataclass
class LiverPipelineResult:
    extracted_report: ExtractedLabReport

    normalized_results: list[
        NormalizedLiverValue
    ]

    analysis: LiverAnalysisResult

    skipped_unreadable: list[str] = field(
        default_factory=list
    )

    out_of_scope_tests: list[str] = field(
        default_factory=list
    )


class LiverPipeline:
    def __init__(
        self,
        extractor: LabImageExtractor,
        analyzer: LiverAnalyzer | None = None,
    ):
        self.extractor = extractor
        self.analyzer = (
            analyzer
            or LiverAnalyzer()
        )

    def run(
        self,
        image_path: str | Path,
    ) -> LiverPipelineResult:

        extracted = self.extractor.extract(
            image_path
        )

        normalized = normalize_liver_results(
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

        return LiverPipelineResult(
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