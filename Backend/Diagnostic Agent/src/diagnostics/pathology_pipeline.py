from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
)

from src.diagnostics.pathology_assessment import (
    PathologyAssessment,
    PathologyAssessmentBuilder,
)

from src.diagnostics.pathology_processor import (
    PathologyProcessor,
    PathologyProcessorResult,
)


@dataclass
class PathologyPipelineResult:
    extracted_report: ExtractedLabReport
    processing: PathologyProcessorResult
    assessment: PathologyAssessment


class PathologyPipeline:
    """
    Unified pathology processing pipeline.

    Image
        -> extraction
        -> pathology processor
        -> pathology assessment

    The assessment is the stable output
    that the future Pathology Agent will use.
    """

    def __init__(
        self,
        extractor,
        processor: PathologyProcessor | None = None,
        assessment_builder: (
            PathologyAssessmentBuilder | None
        ) = None,
    ):
        self.extractor = extractor

        self.processor = (
            processor
            or PathologyProcessor()
        )

        self.assessment_builder = (
            assessment_builder
            or PathologyAssessmentBuilder()
        )

    def run(
        self,
        image_path: str | Path,
    ) -> PathologyPipelineResult:

        report = self.extractor.extract(
            image_path
        )

        processing = self.processor.process(
            report
        )

        assessment = (
            self.assessment_builder.build(
                processing
            )
        )

        return PathologyPipelineResult(
            extracted_report=report,
            processing=processing,
            assessment=assessment,
        )