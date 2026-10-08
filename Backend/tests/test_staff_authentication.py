from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.security.passwords import (
    hash_password,
)
from app.services.staff_access_service import (
    StaffAccessService,
)


PASSWORD = "StrongPassword123!"


class FakeAuthRepository:

    def __init__(
        self,
        *,
        user=None,
        membership=None,
    ):
        self.user = user
        self.membership = membership

        self.email_lookups = []
        self.membership_lookups = []

    def get_user_by_email(
        self,
        *,
        email,
    ):

        self.email_lookups.append(
            email
        )

        return self.user

    def get_active_membership(
        self,
        *,
        user_id,
        provider_id,
    ):

        self.membership_lookups.append(
            {
                "user_id":
                    user_id,
                "provider_id":
                    provider_id,
            }
        )

        return self.membership


def make_user(
    *,
    active=True,
):

    return SimpleNamespace(
        id=uuid4(),
        email="staff@medmind.local",
        password_hash=(
            hash_password(
                PASSWORD
            )
        ),
        is_active=active,
    )


def make_membership(
    *,
    user_id,
    provider_id,
):

    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        provider_id=provider_id,
        role="receptionist",
        doctor_id=None,
        is_active=True,
    )


def test_valid_staff_authentication():

    provider_id = uuid4()

    user = make_user()

    membership = make_membership(
        user_id=user.id,
        provider_id=provider_id,
    )

    repository = FakeAuthRepository(
        user=user,
        membership=membership,
    )

    service = StaffAccessService(
        repository
    )

    authenticated_user, authenticated_membership = (
        service.authenticate_staff(
            provider_id=provider_id,
            email=(
                "  STAFF@MEDMIND.LOCAL "
            ),
            password=PASSWORD,
        )
    )

    assert authenticated_user is user

    assert (
        authenticated_membership
        is membership
    )

    assert repository.email_lookups == [
        "staff@medmind.local"
    ]


def test_wrong_password_rejected():

    user = make_user()

    repository = FakeAuthRepository(
        user=user,
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.authenticate_staff(
            provider_id=uuid4(),
            email="staff@medmind.local",
            password="WrongPassword123!",
        )

    assert (
        exc_info.value.status_code
        == 401
    )

    assert (
        exc_info.value.detail["code"]
        == "INVALID_CREDENTIALS"
    )


def test_inactive_account_rejected():

    user = make_user(
        active=False,
    )

    repository = FakeAuthRepository(
        user=user,
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.authenticate_staff(
            provider_id=uuid4(),
            email="staff@medmind.local",
            password=PASSWORD,
        )

    assert (
        exc_info.value.status_code
        == 401
    )


def test_other_provider_rejected():

    provider_id = uuid4()

    user = make_user()

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

        service.authenticate_staff(
            provider_id=provider_id,
            email="staff@medmind.local",
            password=PASSWORD,
        )

    assert (
        exc_info.value.status_code
        == 403
    )

    assert (
        exc_info.value.detail["code"]
        == "STAFF_ACCESS_DENIED"
    )