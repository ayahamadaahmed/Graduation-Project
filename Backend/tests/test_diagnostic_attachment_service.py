from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentError,
    DiagnosticAttachmentService,
    DiagnosticFileTooLargeError,
    InvalidDiagnosticAttachmentError,
    UnsupportedDiagnosticFileTypeError,
)


JPEG_BYTES = (
    b"\xff\xd8\xff"
    + b"fake-jpeg-content"
)

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    + b"fake-png-content"
)


class FakeSession:

    def __init__(
        self,
        *,
        fail_commit: bool = False,
    ) -> None:

        self.fail_commit = fail_commit
        self.commit_count = 0
        self.rollback_count = 0

    def commit(
        self,
    ) -> None:

        self.commit_count += 1

        if self.fail_commit:
            raise RuntimeError(
                "database unavailable"
            )

    def rollback(
        self,
    ) -> None:

        self.rollback_count += 1


class FakeRepository:

    def __init__(
        self,
        *,
        fail_create: bool = False,
        fail_commit: bool = False,
    ) -> None:

        self.session = FakeSession(
            fail_commit=fail_commit
        )

        self.fail_create = (
            fail_create
        )

        self.created_kwargs = None
        self.lookup_result = None

    def create(
        self,
        **kwargs,
    ):

        if self.fail_create:
            raise RuntimeError(
                "insert failed"
            )

        self.created_kwargs = kwargs

        return SimpleNamespace(
            **kwargs
        )

    def get_by_attachment_id(
        self,
        *,
        provider_id,
        attachment_id,
    ):

        return self.lookup_result


def make_service(
    tmp_path: Path,
    *,
    repository: FakeRepository | None = None,
    max_upload_bytes: int = 1024,
):

    repository = (
        repository
        or FakeRepository()
    )

    service = (
        DiagnosticAttachmentService(
            repository=repository,
            storage_dir=tmp_path,
            max_upload_bytes=(
                max_upload_bytes
            ),
        )
    )

    return (
        service,
        repository,
    )


def test_store_creates_file_and_db_record(
    tmp_path,
):

    service, repository = (
        make_service(
            tmp_path
        )
    )

    provider_id = uuid4()

    attachment = service.store(
        provider_id=provider_id,
        session_id="session-1",
        original_filename="xray.jpeg",
        content_type="image/jpeg",
        data=JPEG_BYTES,
    )

    assert (
        repository.session.commit_count
        == 1
    )

    assert (
        repository.session.rollback_count
        == 0
    )

    assert (
        repository.created_kwargs[
            "provider_id"
        ]
        == provider_id
    )

    assert (
        repository.created_kwargs[
            "content_type"
        ]
        == "image/jpeg"
    )

    assert (
        attachment.attachment_id
        == repository.created_kwargs[
            "attachment_id"
        ]
    )

    stored_path = (
        tmp_path
        / Path(
            attachment.storage_key
        )
    )

    assert stored_path.is_file()

    assert (
        stored_path.read_bytes()
        == JPEG_BYTES
    )


def test_db_failure_removes_stored_file(
    tmp_path,
):

    repository = FakeRepository(
        fail_create=True
    )

    service, repository = (
        make_service(
            tmp_path,
            repository=repository,
        )
    )

    provider_id = uuid4()

    with pytest.raises(
        DiagnosticAttachmentError
    ):

        service.store(
            provider_id=provider_id,
            session_id="session-1",
            original_filename="cbc.png",
            content_type="image/png",
            data=PNG_BYTES,
        )

    assert (
        repository.session.rollback_count
        == 1
    )

    provider_directory = (
        tmp_path
        / str(provider_id)
    )

    remaining_files = (
        list(
            provider_directory.glob("*")
        )
        if provider_directory.exists()
        else []
    )

    assert remaining_files == []


def test_commit_failure_removes_stored_file(
    tmp_path,
):

    repository = FakeRepository(
        fail_commit=True
    )

    service, repository = (
        make_service(
            tmp_path,
            repository=repository,
        )
    )

    provider_id = uuid4()

    with pytest.raises(
        DiagnosticAttachmentError
    ):

        service.store(
            provider_id=provider_id,
            session_id="session-1",
            original_filename="mri.jpg",
            content_type="image/jpeg",
            data=JPEG_BYTES,
        )

    assert (
        repository.session.commit_count
        == 1
    )

    assert (
        repository.session.rollback_count
        == 1
    )

    provider_directory = (
        tmp_path
        / str(provider_id)
    )

    remaining_files = (
        list(
            provider_directory.glob("*")
        )
        if provider_directory.exists()
        else []
    )

    assert remaining_files == []


def test_rejects_content_type_mismatch(
    tmp_path,
):

    service, repository = (
        make_service(
            tmp_path
        )
    )

    with pytest.raises(
        InvalidDiagnosticAttachmentError
    ):

        service.store(
            provider_id=uuid4(),
            session_id="session-1",
            original_filename="fake.jpg",
            content_type="image/jpeg",
            data=PNG_BYTES,
        )

    assert (
        repository.session.commit_count
        == 0
    )


def test_rejects_unsupported_file(
    tmp_path,
):

    service, repository = (
        make_service(
            tmp_path
        )
    )

    with pytest.raises(
        UnsupportedDiagnosticFileTypeError
    ):

        service.store(
            provider_id=uuid4(),
            session_id="session-1",
            original_filename="report.pdf",
            content_type="application/pdf",
            data=b"%PDF-test",
        )

    assert (
        repository.session.commit_count
        == 0
    )


def test_rejects_oversized_file(
    tmp_path,
):

    service, repository = (
        make_service(
            tmp_path,
            max_upload_bytes=5,
        )
    )

    with pytest.raises(
        DiagnosticFileTooLargeError
    ):

        service.store(
            provider_id=uuid4(),
            session_id="session-1",
            original_filename="xray.jpg",
            content_type="image/jpeg",
            data=JPEG_BYTES,
        )

    assert (
        repository.session.commit_count
        == 0
    )