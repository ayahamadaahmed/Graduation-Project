from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.security.rbac import (
    require_staff_roles,
)
from app.security.staff_context import (
    StaffContext,
)


def make_staff(
    role: str,
) -> StaffContext:

    return StaffContext(
        user_id=uuid4(),
        membership_id=uuid4(),
        provider_id=uuid4(),
        role=role,
        doctor_id=None,
    )


def test_allowed_role_passes():

    dependency = require_staff_roles(
        "doctor",
        "provider_admin",
    )

    staff = make_staff(
        "doctor"
    )

    result = dependency(
        staff
    )

    assert result is staff


def test_disallowed_role_rejected():

    dependency = require_staff_roles(
        "doctor",
    )

    staff = make_staff(
        "receptionist"
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        dependency(
            staff
        )

    assert (
        exc_info.value.status_code
        == 403
    )

    assert (
        exc_info.value.detail["code"]
        == "STAFF_PERMISSION_DENIED"
    )


def test_multiple_roles_supported():

    dependency = require_staff_roles(
        "doctor",
        "receptionist",
        "lab_staff",
    )

    staff = make_staff(
        "lab_staff"
    )

    assert (
        dependency(staff)
        is staff
    )


def test_empty_roles_rejected():

    with pytest.raises(
        ValueError
    ):

        require_staff_roles()


def test_unknown_role_rejected():

    with pytest.raises(
        ValueError
    ):

        require_staff_roles(
            "superuser"
        )