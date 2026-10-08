from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi.testclient import (
    TestClient,
)

import src.api.app as api_module


client = TestClient(
    api_module.app
)


class FakePathologyPipeline:

    def __init__(
        self,
    ):
        self.calls = []

    def run(
        self,
        image_path,
    ):

        path = Path(
            image_path
        )

        self.calls.append(
            {
                "path":
                    path,

                "exists_during_call":
                    path.exists(),

                "data":
                    path.read_bytes(),
            }
        )

        return SimpleNamespace(
            extracted_report=(
                SimpleNamespace(
                    document_type="cbc",
                )
            ),

            processing=(
                SimpleNamespace()
            ),

            assessment=(
                SimpleNamespace()
            ),
        )


class FakePersistenceBuilder:

    def __init__(
        self,
    ):
        self.calls = []

    def build(
        self,
        *,
        report,
        processing,
    ):

        self.calls.append(
            {
                "report":
                    report,

                "processing":
                    processing,
            }
        )

        return SimpleNamespace(
            schema_version="1.0",

            document_type="cbc",

            unreadable_fields=[],

            results=[
                {
                    "result_index":
                        0,

                    "panel":
                        "cbc",

                    "raw_name":
                        "Hemoglobin",

                    "canonical_name":
                        "hemoglobin",

                    "value":
                        12.0,

                    "unit":
                        "g/dL",

                    "reference_min":
                        12.0,

                    "reference_max":
                        16.0,

                    "reference_text":
                        None,

                    "flag":
                        "normal",

                    "mapping_status":
                        "mapped",
                }
            ],
        )


@pytest.fixture
def pathology_fakes(
    monkeypatch,
):

    pipeline = (
        FakePathologyPipeline()
    )

    builder = (
        FakePersistenceBuilder()
    )

    monkeypatch.setattr(
        api_module,
        "get_pathology_pipeline",
        lambda: pipeline,
    )

    monkeypatch.setattr(
        api_module,
        "pathology_persistence_builder",
        builder,
    )

    return (
        pipeline,
        builder,
    )


def test_pathology_analyze_success(
    pathology_fakes,
):

    pipeline, builder = (
        pathology_fakes
    )

    response = client.post(
        "/v1/pathology/analyze",

        files={
            "file": (
                "cbc.png",
                b"fake-image-bytes",
                "image/png",
            ),
        },
    )

    assert (
        response.status_code
        == 200
    )

    body = response.json()

    assert (
        body["schema_version"]
        == "1.0"
    )

    assert (
        body["document_type"]
        == "cbc"
    )

    assert (
        len(
            body["results"]
        )
        == 1
    )

    result = (
        body["results"][0]
    )

    assert (
        result["raw_name"]
        == "Hemoglobin"
    )

    assert (
        result["canonical_name"]
        == "hemoglobin"
    )

    assert (
        result["value"]
        == 12.0
    )

    assert (
        result["flag"]
        == "normal"
    )

    assert (
        result["mapping_status"]
        == "mapped"
    )

    assert (
        len(
            pipeline.calls
        )
        == 1
    )

    call = (
        pipeline.calls[0]
    )

    assert (
        call["exists_during_call"]
        is True
    )

    assert (
        call["data"]
        == b"fake-image-bytes"
    )

    # Temporary file must be cleaned.
    assert (
        call["path"].exists()
        is False
    )

    assert (
        len(
            builder.calls
        )
        == 1
    )


def test_pathology_rejects_unsupported_type(
    pathology_fakes,
):

    pipeline, builder = (
        pathology_fakes
    )

    response = client.post(
        "/v1/pathology/analyze",

        files={
            "file": (
                "report.pdf",
                b"fake-pdf",
                "application/pdf",
            ),
        },
    )

    assert (
        response.status_code
        == 415
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "UNSUPPORTED_DIAGNOSTIC_FILE_TYPE"
    )

    assert (
        pipeline.calls
        == []
    )

    assert (
        builder.calls
        == []
    )


def test_pathology_rejects_empty_file(
    pathology_fakes,
):

    pipeline, builder = (
        pathology_fakes
    )

    response = client.post(
        "/v1/pathology/analyze",

        files={
            "file": (
                "cbc.jpg",
                b"",
                "image/jpeg",
            ),
        },
    )

    assert (
        response.status_code
        == 400
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "EMPTY_DIAGNOSTIC_FILE"
    )

    assert (
        pipeline.calls
        == []
    )

    assert (
        builder.calls
        == []
    )


def test_pathology_rejects_file_over_limit(
    pathology_fakes,
    monkeypatch,
):

    pipeline, builder = (
        pathology_fakes
    )

    monkeypatch.setattr(
        api_module,
        "MAX_IMAGE_BYTES",
        4,
    )

    response = client.post(
        "/v1/pathology/analyze",

        files={
            "file": (
                "cbc.jpg",
                b"12345",
                "image/jpeg",
            ),
        },
    )

    assert (
        response.status_code
        == 413
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "DIAGNOSTIC_FILE_TOO_LARGE"
    )

    assert (
        pipeline.calls
        == []
    )

    assert (
        builder.calls
        == []
    )