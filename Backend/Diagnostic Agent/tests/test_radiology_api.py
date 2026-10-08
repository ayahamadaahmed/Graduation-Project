from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi.testclient import (
    TestClient,
)

import src.api.app as api_module

from src.api.app import app

from src.diagnostics.radiology.radiology_processor import (
    RadiologyModality,
)


# ============================================================
# FAKES
# ============================================================


class FakeRadiologyProcessor:

    def __init__(
        self,
    ) -> None:

        self.calls = []

    def process(
        self,
        *,
        image_path,
        modality,
    ):

        image_path = Path(
            image_path
        )

        # Temporary file must exist while
        # inference is executing.
        assert image_path.is_file()

        self.calls.append(
            {
                "image_path":
                    str(image_path),

                "modality":
                    modality,
            }
        )

        return SimpleNamespace(
            modality=modality,
            result=SimpleNamespace(),
        )


class FakeRadiologyAssessmentBuilder:

    def build(
        self,
        processing,
    ):

        return SimpleNamespace(
            modality=(
                processing.modality
            ),

            classification=
                "pituitary",

            probabilities={
                "glioma": 0.02,
                "meningioma": 0.03,
                "notumor": 0.05,
                "pituitary": 0.90,
            },

            confidence=0.90,

            inference_latency_ms=123.4,

            model_name=
                "fake-brain-mri-model",

            model_version=
                "test-1",

            limitations=(
                "Decision-support only.",
            ),
        )


# ============================================================
# FIXTURE
# ============================================================


@pytest.fixture
def client(
    monkeypatch,
):

    processor = (
        FakeRadiologyProcessor()
    )

    builder = (
        FakeRadiologyAssessmentBuilder()
    )

    monkeypatch.setattr(
        api_module,
        "radiology_processor",
        processor,
    )

    monkeypatch.setattr(
        api_module,
        "radiology_assessment_builder",
        builder,
    )

    return (
        TestClient(app),
        processor,
    )


# ============================================================
# VALID REQUEST
# ============================================================


def test_radiology_analyze_returns_structured_result(
    client,
):

    http_client, processor = client

    response = http_client.post(
        "/v1/radiology/analyze",
        data={
            "modality":
                "brain_mri",
        },
        files={
            "file": (
                "brain.png",
                b"fake-image-bytes",
                "image/png",
            ),
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["modality"]
        == "brain_mri"
    )

    assert (
        body["classification"]
        == "pituitary"
    )

    assert (
        body["confidence"]
        == 0.90
    )

    assert (
        body["probabilities"]
        ["pituitary"]
        == 0.90
    )

    assert (
        body["model_name"]
        == "fake-brain-mri-model"
    )

    assert len(
        processor.calls
    ) == 1

    assert (
        processor.calls[0]
        ["modality"]
        == RadiologyModality.BRAIN_MRI
    )

    # Temporary file must have been deleted
    # after processing finished.
    temp_path = Path(
        processor.calls[0][
            "image_path"
        ]
    )

    assert not temp_path.exists()


# ============================================================
# UNSUPPORTED MODALITY
# ============================================================


def test_radiology_rejects_unknown_modality(
    client,
):

    http_client, processor = client

    response = http_client.post(
        "/v1/radiology/analyze",
        data={
            "modality":
                "pet_scan",
        },
        files={
            "file": (
                "scan.png",
                b"fake-image-bytes",
                "image/png",
            ),
        },
    )

    assert response.status_code == 400

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "UNSUPPORTED_RADIOLOGY_MODALITY"
    )

    assert processor.calls == []


# ============================================================
# UNSUPPORTED FILE TYPE
# ============================================================


def test_radiology_rejects_unsupported_media_type(
    client,
):

    http_client, processor = client

    response = http_client.post(
        "/v1/radiology/analyze",
        data={
            "modality":
                "brain_mri",
        },
        files={
            "file": (
                "scan.pdf",
                b"%PDF-test",
                "application/pdf",
            ),
        },
    )

    assert response.status_code == 415

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "UNSUPPORTED_DIAGNOSTIC_FILE_TYPE"
    )

    assert processor.calls == []


# ============================================================
# EMPTY FILE
# ============================================================


def test_radiology_rejects_empty_file(
    client,
):

    http_client, processor = client

    response = http_client.post(
        "/v1/radiology/analyze",
        data={
            "modality":
                "kidney_ct",
        },
        files={
            "file": (
                "kidney.jpg",
                b"",
                "image/jpeg",
            ),
        },
    )

    assert response.status_code == 400

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "EMPTY_DIAGNOSTIC_FILE"
    )

    assert processor.calls == []