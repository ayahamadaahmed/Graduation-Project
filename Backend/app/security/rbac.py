from collections.abc import Callable

from fastapi import (
    HTTPException,
    status,
)

from app.api.dependencies import (
    CurrentStaff,
)
from app.security.staff_context import (
    StaffContext,
)


VALID_STAFF_ROLES = frozenset(
    {
        "provider_admin",
        "doctor",
        "receptionist",
        "lab_staff",
    }
)


def require_staff_roles(
    *allowed_roles: str,
) -> Callable[..., StaffContext]:

    allowed = frozenset(
        allowed_roles
    )

    if not allowed:
        raise ValueError(
            "At least one staff role "
            "must be required."
        )

    unknown = (
        allowed
        - VALID_STAFF_ROLES
    )

    if unknown:
        raise ValueError(
            "Unknown staff role(s): "
            + ", ".join(
                sorted(unknown)
            )
        )

    def dependency(
        staff: CurrentStaff,
    ) -> StaffContext:

        if staff.role not in allowed:

            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail={
                    "code":
                        "STAFF_PERMISSION_DENIED",

                    "message": (
                        "This staff role is not "
                        "allowed to perform "
                        "this operation."
                    ),
                },
            )

        return staff

    return dependency