from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.api.dependencies import (
    CurrentProvider,
    CurrentStaff,
    StaffAccessServiceDependency,
)
from app.core.config import (
    get_settings,
)
from app.schemas.auth import (
    StaffCurrentResponse,
    StaffLoginRequest,
    StaffLoginResponse,
)
from app.security.login_throttle import (
    LoginThrottle,
    get_login_throttle,
)
from app.security.tokens import (
    create_access_token,
)


router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post(
    "/login",
    response_model=StaffLoginResponse,
    status_code=status.HTTP_200_OK,
)
def login_staff(
    data: StaffLoginRequest,
    provider: CurrentProvider,
    service: StaffAccessServiceDependency,
    throttle: Annotated[
        LoginThrottle,
        Depends(get_login_throttle),
    ],
) -> StaffLoginResponse:

    retry_after = throttle.retry_after(
        data.email
    )

    if retry_after is not None:

        raise HTTPException(
            status_code=(
                status.HTTP_429_TOO_MANY_REQUESTS
            ),
            detail={
                "code":
                    "LOGIN_TEMPORARILY_LOCKED",

                "message": (
                    "Too many failed login attempts. "
                    "Try again later."
                ),
            },
            headers={
                "Retry-After":
                    str(retry_after),
            },
        )

    try:

        user, membership = (
            service.authenticate_staff(
                provider_id=provider.id,
                email=data.email,
                password=data.password,
            )
        )

    except HTTPException as exc:

        # Only wrong email/password counts; a correct password without
        # access to this provider (403) is not a guessing failure.
        if (
            isinstance(exc.detail, dict)
            and exc.detail.get("code")
            == "INVALID_CREDENTIALS"
        ):
            throttle.register_failure(
                data.email
            )

        raise

    throttle.reset(
        data.email
    )

    settings = get_settings()

    token = create_access_token(
        user_id=user.id,
        membership_id=membership.id,
        provider_id=provider.id,
        settings=settings,
    )

    return StaffLoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=(
            settings
            .jwt_access_token_minutes
            * 60
        ),
        user_id=user.id,
        membership_id=membership.id,
        provider_id=provider.id,
        role=membership.role,
    )

@router.get(
    "/me",
    response_model=StaffCurrentResponse,
)
def get_current_staff_profile(
    staff: CurrentStaff,
) -> StaffCurrentResponse:

    return StaffCurrentResponse(
        user_id=staff.user_id,
        membership_id=staff.membership_id,
        provider_id=staff.provider_id,
        role=staff.role,
        doctor_id=staff.doctor_id,
    )