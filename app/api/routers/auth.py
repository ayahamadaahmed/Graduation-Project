from fastapi import (
    APIRouter,
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
) -> StaffLoginResponse:

    user, membership = (
        service.authenticate_staff(
            provider_id=provider.id,
            email=data.email,
            password=data.password,
        )
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