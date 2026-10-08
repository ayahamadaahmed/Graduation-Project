from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    ExtractedLabValue,
)

from src.diagnostics.pathology_pipeline import (
    PathologyPipeline,
)

from src.diagnostics.pathology_schema import (
    pathology_result_to_schema,
)


class FakeExtractor:
    def extract(self, image_path):
        return ExtractedLabReport(
            document_type="mixed_lab_report",
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
                ExtractedLabValue(
                    raw_name="HbA1c",
                    value=5.4,
                    unit="%",
                    reference_min=4,
                    reference_max=5.6,
                ),
            ],
        )


def test_pathology_response_schema():
    pipeline = PathologyPipeline(
        extractor=FakeExtractor()
    )

    result = pipeline.run(
        "fake.png"
    )

    response = pathology_result_to_schema(
        result
    )

    assert response.schema_version == "1.0"

    assert (
        response.document_type
        == "mixed_lab_report"
    )

    assert set(
        response.detected_panels
    ) == {
        "cbc",
        "glycemic",
    }

    abnormal_names = {
        item.name
        for item
        in response.abnormal_findings
    }

    assert "hemoglobin" in abnormal_names

    normal_names = {
        item.name
        for item
        in response.normal_findings
    }

    assert "hba1c" in normal_names


def test_schema_serializes_to_json():
    result = PathologyPipeline(
        extractor=FakeExtractor()
    ).run(
        "fake.png"
    )

    response = pathology_result_to_schema(
        result
    )

    payload = response.model_dump()

    assert payload[
        "schema_version"
    ] == "1.0"

    assert isinstance(
        payload["detected_panels"],
        list,
    )

    assert isinstance(
        payload["abnormal_findings"],
        list,
    )