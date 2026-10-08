from pathlib import Path

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    ExtractedLabValue,
)

from src.diagnostics.pathology_pipeline import (
    PathologyPipeline,
)


class FakeLabExtractor:
    def __init__(self):
        self.calls = 0

    def extract(
        self,
        image_path,
    ) -> ExtractedLabReport:

        self.calls += 1

        return ExtractedLabReport(
            document_type="mixed_lab_report",
            results=[
                ExtractedLabValue(
                    raw_name="HGB",
                    value=12,
                    unit="g/dL",
                    reference_min=11,
                    reference_max=16,
                ),
                ExtractedLabValue(
                    raw_name="MCV",
                    value=85,
                    unit="fL",
                    reference_min=80,
                    reference_max=100,
                ),
                ExtractedLabValue(
                    raw_name="WBC",
                    value=7,
                    unit="10^3/uL",
                    reference_min=4,
                    reference_max=11,
                ),
                ExtractedLabValue(
                    raw_name="PLT",
                    value=250,
                    unit="10^3/uL",
                    reference_min=150,
                    reference_max=450,
                ),
                ExtractedLabValue(
                    raw_name="HbA1c",
                    value=5.4,
                    unit="%",
                    reference_min=4,
                    reference_max=5.6,
                ),
                ExtractedLabValue(
                    raw_name="Serum Creatinine",
                    value=0.9,
                    unit="mg/dL",
                    reference_min=0.6,
                    reference_max=1.2,
                ),
                ExtractedLabValue(
                    raw_name="SGPT (ALT)",
                    value=30,
                    unit="U/L",
                    reference_min=0,
                    reference_max=40,
                ),
                ExtractedLabValue(
                    raw_name="LDL-C",
                    value=100,
                    unit="mg/dL",
                    reference_min=0,
                    reference_max=130,
                ),
            ],
        )


def test_unified_pathology_pipeline():
    extractor = FakeLabExtractor()

    pipeline = PathologyPipeline(
        extractor=extractor
    )

    result = pipeline.run(
        Path("fake_report.png")
    )

    assert extractor.calls == 1

    assert set(
        result.processing.detected_panels
    ) == {
        "cbc",
        "glycemic",
        "renal",
        "liver",
        "lipid",
    }

    assert (
        result.processing.cbc
        is not None
    )

    assert (
        result.processing.glycemic
        is not None
    )

    assert (
        result.processing.renal
        is not None
    )

    assert (
        result.processing.liver
        is not None
    )

    assert (
        result.processing.lipid
        is not None
    )


def test_pipeline_preserves_unmapped_test():
    class Extractor:
        def extract(self, image_path):
            return ExtractedLabReport(
                document_type="lab",
                results=[
                    ExtractedLabValue(
                        raw_name="Unknown XYZ",
                        value=10,
                        unit="unit",
                    )
                ],
            )

    result = PathologyPipeline(
        extractor=Extractor()
    ).run(
        "fake.png"
    )

    assert result.processing.unmapped_tests == [
        "Unknown XYZ"
    ]

def test_pipeline_builds_unified_assessment():
    class Extractor:
        def extract(self, image_path):
            return ExtractedLabReport(
                document_type="mixed",
                results=[
                    ExtractedLabValue(
                        raw_name="HGB",
                        value=10,
                        unit="g/dL",
                        reference_min=12,
                        reference_max=16,
                    ),
                    ExtractedLabValue(
                        raw_name="MCV",
                        value=85,
                        unit="fL",
                        reference_min=80,
                        reference_max=100,
                    ),
                    ExtractedLabValue(
                        raw_name="WBC",
                        value=7,
                        unit="10^3/uL",
                        reference_min=4,
                        reference_max=11,
                    ),
                    ExtractedLabValue(
                        raw_name="PLT",
                        value=250,
                        unit="10^3/uL",
                        reference_min=150,
                        reference_max=450,
                    ),
                ],
            )

    result = PathologyPipeline(
        extractor=Extractor()
    ).run(
        "fake.png"
    )

    assert result.assessment is not None

    assert (
        "cbc"
        in result.assessment.detected_panels
    )

    abnormal_names = {
        finding.name
        for finding
        in result.assessment.abnormal_findings
    }

    assert "hemoglobin" in abnormal_names    