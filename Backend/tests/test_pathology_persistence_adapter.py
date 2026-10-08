from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.pathology_persistence import (
    PathologyPersistenceRequest,
)

from app.services.pathology_persistence_adapter import (
    DuplicatePathologyPersistenceError,
    PathologyPersistenceAdapter,
)


class FakeAttachmentService:

    def __init__(
        self,
        attachment,
    ) -> None:

        self.attachment = attachment
        self.calls = []

    def get(
        self,
        *,
        provider_id,
        attachment_id,
    ):

        self.calls.append(
            {
                "provider_id": provider_id,
                "attachment_id": (
                    attachment_id
                ),
            }
        )

        return self.attachment


class FakeLabRepository:

    def __init__(
        self,
        existing=None,
    ) -> None:

        self.existing = existing
        self.calls = []

    def get_report_by_attachment(
        self,
        *,
        provider_id,
        diagnostic_attachment_id,
    ):

        self.calls.append(
            {
                "provider_id": provider_id,
                "diagnostic_attachment_id": (
                    diagnostic_attachment_id
                ),
            }
        )

        return self.existing


class FakeLabPersistenceService:

    def __init__(
        self,
        *,
        existing=None,
    ) -> None:

        self.repository = FakeLabRepository(
            existing=existing
        )

        self.saved_kwargs = None

    def save_processed_report(
        self,
        **kwargs,
    ):

        self.saved_kwargs = kwargs

        return SimpleNamespace(
            id=uuid4(),
            status="processed",
        )


def make_request():

    return PathologyPersistenceRequest(
        schema_version="1.0",
        attachment_id=(
            "a" * 32
        ),
        document_type="cbc",
        unreadable_fields=[],
        results=[
            {
                "result_index": 0,
                "panel": "cbc",
                "raw_name": "HGB",
                "canonical_name":
                    "hemoglobin",
                "value": "10.0",
                "unit": "g/dL",
                "reference_min": "12",
                "reference_max": "16",
                "reference_text": "12 - 16",
                "flag": "low",
                "mapping_status": "mapped",
            }
        ],
    )


def test_persists_using_attachment_identity():

    provider_id = uuid4()
    patient_id = uuid4()
    encounter_id = uuid4()

    attachment = SimpleNamespace(
        id=uuid4(),
        patient_id=patient_id,
        encounter_id=encounter_id,
    )

    attachment_service = (
        FakeAttachmentService(
            attachment
        )
    )

    lab_service = (
        FakeLabPersistenceService()
    )

    adapter = (
        PathologyPersistenceAdapter(
            attachment_service=(
                attachment_service
            ),
            lab_persistence_service=(
                lab_service
            ),
        )
    )

    report = adapter.persist(
        provider_id=provider_id,
        request=make_request(),
    )

    assert report.status == "processed"

    assert (
        lab_service
        .saved_kwargs["provider_id"]
        == provider_id
    )

    assert (
        lab_service
        .saved_kwargs[
            "diagnostic_attachment_id"
        ]
        == attachment.id
    )

    assert (
        lab_service
        .saved_kwargs["patient_id"]
        == patient_id
    )

    assert (
        lab_service
        .saved_kwargs["encounter_id"]
        == encounter_id
    )


def test_converts_result_contract():

    attachment = SimpleNamespace(
        id=uuid4(),
        patient_id=None,
        encounter_id=None,
    )

    lab_service = (
        FakeLabPersistenceService()
    )

    adapter = PathologyPersistenceAdapter(
        attachment_service=(
            FakeAttachmentService(
                attachment
            )
        ),
        lab_persistence_service=(
            lab_service
        ),
    )

    adapter.persist(
        provider_id=uuid4(),
        request=make_request(),
    )

    result = (
        lab_service
        .saved_kwargs["results"][0]
    )

    assert result.result_index == 0
    assert result.panel == "cbc"
    assert result.raw_name == "HGB"

    assert (
        result.canonical_name
        == "hemoglobin"
    )

    assert result.flag == "low"

    assert (
        result.mapping_status
        == "mapped"
    )


def test_rejects_duplicate_attachment():

    attachment = SimpleNamespace(
        id=uuid4(),
        patient_id=None,
        encounter_id=None,
    )

    existing_report = SimpleNamespace(
        id=uuid4()
    )

    lab_service = (
        FakeLabPersistenceService(
            existing=existing_report
        )
    )

    adapter = PathologyPersistenceAdapter(
        attachment_service=(
            FakeAttachmentService(
                attachment
            )
        ),
        lab_persistence_service=(
            lab_service
        ),
    )

    with pytest.raises(
        DuplicatePathologyPersistenceError
    ):

        adapter.persist(
            provider_id=uuid4(),
            request=make_request(),
        )

    assert (
        lab_service.saved_kwargs
        is None
    )