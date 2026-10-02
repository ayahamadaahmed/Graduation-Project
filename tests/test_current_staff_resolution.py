from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.staff_access_service import (
    StaffAccessService,
)


class FakeAuthRepository:

    def __init__(
        self,
        *,
        user=None,
        membership=None,
    ):
        self.user = user
        self.membership = membership

        self.user_calls = []
        self.membership_calls = []

    def get_active_user_by_id(
        self,
        *,
        user_id,
    ):

        self.user_calls.append(
            user_id
        )

        return self.user

    def get_active_membership_by_identity(
        self,
        *,
        membership_id,
        user_id,
        provider_id,
    ):

        self.membership_calls.append(
            {
                "membership_id":
                    membership_id,
                "user_id":
                    user_id,
                "provider_id":
                    provider_id,
            }
        )

        return self.membership


def test_valid_staff_session_passes():

    provider_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()

    user = SimpleNamespace(
        id=user_id,
        is_active=True,
    )

    membership = SimpleNamespace(
        id=membership_id,
        user_id=user_id,
        provider_id=provider_id,
        role="receptionist",
        is_active=True,
    )

    repository = FakeAuthRepository(
        user=user,
        membership=membership,
    )

    service = StaffAccessService(
        repository
    )

    result_user, result_membership = (
        service.resolve_current_staff(
            provider_id=provider_id,
            user_id=user_id,
            membership_id=membership_id,
            token_provider_id=provider_id,
        )
    )

    assert result_user is user
    assert result_membership is membership


def test_token_tenant_mismatch_rejected():

    repository = FakeAuthRepository()

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.resolve_current_staff(
            provider_id=uuid4(),
            user_id=uuid4(),
            membership_id=uuid4(),
            token_provider_id=uuid4(),
        )

    assert (
        exc_info.value.status_code
        == 403
    )

    assert (
        exc_info.value.detail["code"]
        == "STAFF_TENANT_MISMATCH"
    )

    assert repository.user_calls == []


def test_disabled_user_rejected():

    provider_id = uuid4()

    repository = FakeAuthRepository(
        user=None,
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.resolve_current_staff(
            provider_id=provider_id,
            user_id=uuid4(),
            membership_id=uuid4(),
            token_provider_id=provider_id,
        )

    assert (
        exc_info.value.status_code
        == 401
    )

    assert (
        exc_info.value.detail["code"]
        == "INVALID_STAFF_SESSION"
    )


def test_disabled_membership_rejected():

    provider_id = uuid4()
    user_id = uuid4()

    user = SimpleNamespace(
        id=user_id,
        is_active=True,
    )

    repository = FakeAuthRepository(
        user=user,
        membership=None,
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.resolve_current_staff(
            provider_id=provider_id,
            user_id=user_id,
            membership_id=uuid4(),
            token_provider_id=provider_id,
        )

    assert (
        exc_info.value.status_code
        == 401
    )

    assert (
        exc_info.value.detail["code"]
        == "INVALID_STAFF_SESSION"
    )