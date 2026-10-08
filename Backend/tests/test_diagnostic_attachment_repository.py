from uuid import uuid4

from app.models.diagnostic_attachment import (
    DiagnosticAttachment,
)

from app.repositories.diagnostic_attachment_repository import (
    DiagnosticAttachmentRepository,
)


class FakeSession:

    def __init__(self) -> None:
        self.added = []
        self.deleted = []
        self.flush_count = 0
        self.scalar_result = None

    def add(
        self,
        value,
    ) -> None:
        self.added.append(
            value
        )

    def delete(
        self,
        value,
    ) -> None:
        self.deleted.append(
            value
        )

    def flush(
        self,
    ) -> None:
        self.flush_count += 1

    def scalar(
        self,
        statement,
    ):
        return self.scalar_result


def make_attachment() -> DiagnosticAttachment:

    return DiagnosticAttachment(
        id=uuid4(),
        attachment_id="a" * 32,
        provider_id=uuid4(),
        patient_id=None,
        encounter_id=None,
        session_id="session-1",
        original_filename="cbc.png",
        content_type="image/png",
        size_bytes=123,
        sha256="b" * 64,
        storage_key=(
            "clinic-001/"
            + ("a" * 32)
            + ".png"
        ),
        status="stored",
    )


def test_create_attachment():

    session = FakeSession()

    repository = (
        DiagnosticAttachmentRepository(
            session
        )
    )

    provider_id = uuid4()

    attachment = repository.create(
        attachment_id="a" * 32,
        provider_id=provider_id,
        session_id="session-1",
        original_filename="cbc.png",
        content_type="image/png",
        size_bytes=123,
        sha256="b" * 64,
        storage_key=(
            "clinic-001/"
            + ("a" * 32)
            + ".png"
        ),
    )

    assert (
        session.added
        == [attachment]
    )

    assert (
        session.flush_count
        == 1
    )

    assert (
        attachment.provider_id
        == provider_id
    )

    assert (
        attachment.patient_id
        is None
    )

    assert (
        attachment.encounter_id
        is None
    )

    assert (
        attachment.status
        == "stored"
    )


def test_get_returns_scalar_result():

    session = FakeSession()

    expected = make_attachment()

    session.scalar_result = (
        expected
    )

    repository = (
        DiagnosticAttachmentRepository(
            session
        )
    )

    result = (
        repository
        .get_by_attachment_id(
            provider_id=(
                expected.provider_id
            ),
            attachment_id=(
                expected.attachment_id
            ),
        )
    )

    assert result is expected


def test_bind_to_patient():

    session = FakeSession()

    repository = (
        DiagnosticAttachmentRepository(
            session
        )
    )

    attachment = make_attachment()
    patient_id = uuid4()

    result = repository.bind_to_patient(
        attachment=attachment,
        patient_id=patient_id,
    )

    assert (
        result.patient_id
        == patient_id
    )

    assert (
        session.flush_count
        == 1
    )


def test_bind_to_encounter():

    session = FakeSession()

    repository = (
        DiagnosticAttachmentRepository(
            session
        )
    )

    attachment = make_attachment()
    encounter_id = uuid4()

    result = (
        repository.bind_to_encounter(
            attachment=attachment,
            encounter_id=encounter_id,
        )
    )

    assert (
        result.encounter_id
        == encounter_id
    )

    assert (
        session.flush_count
        == 1
    )


def test_delete_attachment():

    session = FakeSession()

    repository = (
        DiagnosticAttachmentRepository(
            session
        )
    )

    attachment = make_attachment()

    repository.delete(
        attachment
    )

    assert (
        session.deleted
        == [attachment]
    )

    assert (
        session.flush_count
        == 1
    )