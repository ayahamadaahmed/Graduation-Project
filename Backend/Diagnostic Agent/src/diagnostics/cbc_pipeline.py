from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.diagnostics.cbc_engine import (
    CBCAnalysisResult,
    CBCAnalyzer,
)

from src.diagnostics.lab_types import (
    LabValue,
)
from src.diagnostics.cbc_normalizer import (
    NormalizedLabValue,
    find_unmapped_cbc_results,
    normalize_cbc_results,
)
from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    LabImageExtractor,
)


@dataclass
class CBCPipelineResult:
    extracted_report: ExtractedLabReport
    normalized_results: list[NormalizedLabValue]
    analysis: CBCAnalysisResult

    skipped_unreadable: list[str] = field(
        default_factory=list
    )

    unmapped_tests: list[str] = field(
        default_factory=list
    )


class CBCPipeline:
    def __init__(
        self,
        extractor: LabImageExtractor,
        analyzer: CBCAnalyzer | None = None,
    ):
        self.extractor = extractor
        self.analyzer = analyzer or CBCAnalyzer()

    def run(
        self,
        image_path: str | Path,
    ) -> CBCPipelineResult:

        extracted = self.extractor.extract(
            image_path
        )

        normalized = normalize_cbc_results(
            extracted.results
        )

        unmapped = find_unmapped_cbc_results(
            extracted.results
        )
        
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
                    reference_min=result.reference_min,
                    reference_max=result.reference_max,
                )
            )

        analysis = self.analyzer.analyze(
            analyzer_values
        )

        return CBCPipelineResult(
            extracted_report=extracted,
            normalized_results=normalized,
            analysis=analysis,
            skipped_unreadable=skipped_unreadable,
            unmapped_tests=[
                result.raw_name
                for result in unmapped
            ],
        )