from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.radiology_persistence import (
    RadiologyPersistenceRequest,
)

from app.services.radiology_persistence_adapter import (
    DuplicateRadiologyPersistenceError,
    RadiologyPersistenceAdapter,
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
                "provider_id":
                    provider_id,
                "attachment_id":
                    attachment_id,
            }
        )

        return self.attachment


class FakeRepository:

    def __init__(
        self,
    ) -> None:

        self.existing = None
        self.calls = []

    def get_report_by_attachment(
        self,
        *,
        provider_id,
        diagnostic_attachment_id,
    ):

        self.calls.append(
            {
                "provider_id":
                    provider_id,
                "diagnostic_attachment_id":
                    diagnostic_attachment_id,
            }
        )

        return self.existing


class FakeRadiologyPersistenceService:

    def __init__(
        self,
    ) -> None:

        self.repository = (
            FakeRepository()
        )

        self.calls = []

    def save_processed_report(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        return SimpleNamespace(
            id=uuid4(),
            status="processed",
        )


def make_request():

    return RadiologyPersistenceRequest(
        schema_version="1.0",
        attachment_id=(
            "a" * 32
        ),
        modality="chest_xray",
        classification="normal",
        probabilities={
            "normal":
                Decimal("0.7836"),
            "pneumonia":
                Decimal("0.2164"),
        },
        confidence=Decimal(
            "0.7836"
        ),
        inference_latency_ms=Decimal(
            "271.400"
        ),
        model_name=(
            "medmind_chest_xray"
        ),
        model_version="1.0",
        limitations=[
            (
                "Decision-support "
                "classification only."
            ),
        ],
    )


def test_persists_using_attachment_identity():

    provider_id = uuid4()
    patient_id = uuid4()
    encounter_id = uuid4()
    attachment_internal_id = uuid4()

    attachment = SimpleNamespace(
        id=attachment_internal_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
    )

    attachment_service = (
        FakeAttachmentService(
            attachment
        )
    )

    persistence_service = (
        FakeRadiologyPersistenceService()
    )

    adapter = (
        RadiologyPersistenceAdapter(
            attachment_service=(
                attachment_service
            ),
            radiology_persistence_service=(
                persistence_service
            ),
        )
    )

    request = make_request()

    report = adapter.persist(
        provider_id=provider_id,
        request=request,
    )

    assert report.status == "processed"

    assert attachment_service.calls == [
        {
            "provider_id":
                provider_id,
            "attachment_id":
                request.attachment_id,
        }
    ]

    assert len(
        persistence_service.calls
    ) == 1

    call = (
        persistence_service.calls[0]
    )

    assert (
        call["provider_id"]
        == provider_id
    )

    assert (
        call[
            "diagnostic_attachment_id"
        ]
        == attachment_internal_id
    )

    assert (
        call["patient_id"]
        == patient_id
    )

    assert (
        call["encounter_id"]
        == encounter_id
    )

    assert (
        call["modality"]
        == "chest_xray"
    )

    assessment = (
        call["assessment"]
    )

    assert (
        assessment.classification
        == "normal"
    )

    assert (
        assessment.confidence
        == Decimal("0.7836")
    )

    assert assessment.probabilities == {
        "normal":
            Decimal("0.7836"),
        "pneumonia":
            Decimal("0.2164"),
    }


def test_duplicate_report_is_rejected():

    provider_id = uuid4()

    attachment = SimpleNamespace(
        id=uuid4(),
        patient_id=None,
        encounter_id=None,
    )

    attachment_service = (
        FakeAttachmentService(
            attachment
        )
    )

    persistence_service = (
        FakeRadiologyPersistenceService()
    )

    persistence_service.repository.existing = (
        SimpleNamespace(
            id=uuid4(),
        )
    )

    adapter = (
        RadiologyPersistenceAdapter(
            attachment_service=(
                attachment_service
            ),
            radiology_persistence_service=(
                persistence_service
            ),
        )
    )

    with pytest.raises(
        DuplicateRadiologyPersistenceError
    ):
        adapter.persist(
            provider_id=provider_id,
            request=make_request(),
        )

    assert (
        persistence_service.calls
        == []
    )


def test_repository_lookup_is_tenant_scoped():

    provider_id = uuid4()
    attachment_internal_id = uuid4()

    attachment = SimpleNamespace(
        id=attachment_internal_id,
        patient_id=None,
        encounter_id=None,
    )

    attachment_service = (
        FakeAttachmentService(
            attachment
        )
    )

    persistence_service = (
        FakeRadiologyPersistenceService()
    )

    adapter = (
        RadiologyPersistenceAdapter(
            attachment_service=(
                attachment_service
            ),
            radiology_persistence_service=(
                persistence_service
            ),
        )
    )

    adapter.persist(
        provider_id=provider_id,
        request=make_request(),
    )

    assert (
        persistence_service
        .repository
        .calls
    ) == [
        {
            "provider_id":
                provider_id,
            "diagnostic_attachment_id":
                attachment_internal_id,
        }
    ]