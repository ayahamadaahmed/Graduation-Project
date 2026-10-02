from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.security.passwords import (
    verify_password,
)
from app.services.staff_access_service import (
    StaffAccessService,
)


class FakeSession:

    def __init__(self):
        self.commit_count = 0
        self.rollback_count = 0
        self.refresh_count = 0

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def refresh(self, _obj):
        self.refresh_count += 1


class FakeAuthRepository:

    def __init__(
        self,
        *,
        doctor_belongs=True,
        existing_user=None,
        fail_membership=False,
    ):
        self.session = FakeSession()

        self.doctor_belongs = (
            doctor_belongs
        )

        self.existing_user = (
            existing_user
        )

        self.fail_membership = (
            fail_membership
        )

        self.doctor_calls = []
        self.email_lookups = []

        self.added_users = []
        self.added_memberships = []

    def doctor_belongs_to_provider(
        self,
        *,
        provider_id,
        doctor_id,
    ):

        self.doctor_calls.append(
            {
                "provider_id":
                    provider_id,
                "doctor_id":
                    doctor_id,
            }
        )

        return self.doctor_belongs

    def get_user_by_email(
        self,
        *,
        email,
    ):

        self.email_lookups.append(
            email
        )

        return self.existing_user

    def add_user(
        self,
        user,
    ):

        self.added_users.append(
            user
        )

        return user

    def add_membership(
        self,
        membership,
    ):

        if self.fail_membership:
            raise RuntimeError(
                "membership insert failed"
            )

        self.added_memberships.append(
            membership
        )

        return membership


# ============================================================
# MEMBERSHIP VALIDATION
# ============================================================

def test_doctor_membership_same_provider_passes():

    repository = FakeAuthRepository(
        doctor_belongs=True,
    )

    service = StaffAccessService(
        repository
    )

    provider_id = uuid4()
    doctor_id = uuid4()

    service.validate_membership_assignment(
        provider_id=provider_id,
        role="doctor",
        doctor_id=doctor_id,
    )

    assert repository.doctor_calls == [
        {
            "provider_id":
                provider_id,
            "doctor_id":
                doctor_id,
        }
    ]


def test_doctor_membership_other_provider_rejected():

    repository = FakeAuthRepository(
        doctor_belongs=False,
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.validate_membership_assignment(
            provider_id=uuid4(),
            role="doctor",
            doctor_id=uuid4(),
        )

    assert (
        exc_info.value.status_code
        == 404
    )

    assert (
        exc_info.value.detail["code"]
        == "DOCTOR_NOT_FOUND_FOR_PROVIDER"
    )


# ============================================================
# ACCOUNT CREATION
# ============================================================

def test_create_receptionist_account():

    repository = FakeAuthRepository()

    service = StaffAccessService(
        repository
    )

    provider_id = uuid4()

    user, membership = (
        service.create_staff_account(
            provider_id=provider_id,
            email=(
                "  Receptionist@MedMind.Local  "
            ),
            password=(
                "StrongPassword123!"
            ),
            role="receptionist",
        )
    )

    assert (
        user.email
        == "receptionist@medmind.local"
    )

    assert verify_password(
        "StrongPassword123!",
        user.password_hash,
    )

    assert membership.provider_id == (
        provider_id
    )

    assert membership.role == (
        "receptionist"
    )

    assert membership.doctor_id is None

    assert (
        repository.session.commit_count
        == 1
    )

    assert (
        repository.session.rollback_count
        == 0
    )


def test_create_doctor_account():

    repository = FakeAuthRepository(
        doctor_belongs=True,
    )

    service = StaffAccessService(
        repository
    )

    provider_id = uuid4()
    doctor_id = uuid4()

    user, membership = (
        service.create_staff_account(
            provider_id=provider_id,
            email="doctor@medmind.local",
            password=(
                "StrongPassword123!"
            ),
            role="doctor",
            doctor_id=doctor_id,
        )
    )

    assert membership.provider_id == (
        provider_id
    )

    assert membership.doctor_id == (
        doctor_id
    )

    assert membership.user_id == (
        user.id
    )

    assert (
        repository.session.commit_count
        == 1
    )


def test_duplicate_email_rejected():

    repository = FakeAuthRepository(
        existing_user=object(),
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.create_staff_account(
            provider_id=uuid4(),
            email="EXISTING@MEDMIND.LOCAL",
            password=(
                "StrongPassword123!"
            ),
            role="receptionist",
        )

    assert (
        exc_info.value.status_code
        == 409
    )

    assert (
        exc_info.value.detail["code"]
        == "STAFF_ACCOUNT_EXISTS"
    )

    assert repository.email_lookups == [
        "existing@medmind.local"
    ]

    assert (
        repository.session.commit_count
        == 0
    )

    assert (
        repository.session.rollback_count
        == 1
    )


def test_cross_tenant_doctor_account_rejected():

    repository = FakeAuthRepository(
        doctor_belongs=False,
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.create_staff_account(
            provider_id=uuid4(),
            email="doctor@medmind.local",
            password=(
                "StrongPassword123!"
            ),
            role="doctor",
            doctor_id=uuid4(),
        )

    assert (
        exc_info.value.detail["code"]
        == "DOCTOR_NOT_FOUND_FOR_PROVIDER"
    )

    assert repository.added_users == []

    assert (
        repository.session.commit_count
        == 0
    )

    assert (
        repository.session.rollback_count
        == 1
    )


def test_membership_failure_rolls_back_account():

    repository = FakeAuthRepository(
        fail_membership=True,
    )

    service = StaffAccessService(
        repository
    )

    with pytest.raises(
        RuntimeError
    ):

        service.create_staff_account(
            provider_id=uuid4(),
            email="staff@medmind.local",
            password=(
                "StrongPassword123!"
            ),
            role="receptionist",
        )

    # User insert was attempted.
    assert len(
        repository.added_users
    ) == 1

    # But transaction was never committed.
    assert (
        repository.session.commit_count
        == 0
    )

    assert (
        repository.session.rollback_count
        == 1
    )