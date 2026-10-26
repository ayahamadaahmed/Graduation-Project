from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.api.dependencies import (
    CatalogServiceDependency,
)
from app.schemas.public_catalog import (
    PublicBranchOut,
    PublicProviderOut,
)


router = APIRouter(
    prefix="/public",
    tags=["public-catalog"],
)

# API Blueprint paths (GET /providers, GET /providers/{id}/branches):
# the same handlers as /public/..., no prefix of their own.
blueprint_router = APIRouter(
    tags=["public-catalog"],
)


@router.get(
    "/providers",
    response_model=(
        list[PublicProviderOut]
    ),
)
@blueprint_router.get(
    "/providers",
    response_model=(
        list[PublicProviderOut]
    ),
)
def list_public_providers(
    service: CatalogServiceDependency,
    org_type: Literal[
        "clinic",
        "hospital",
        "diagnostic_lab",
    ] | None = Query(
        default=None,
        description=(
            "Optional filter: clinic, hospital or diagnostic_lab. "
            "Omitted: every publicly visible provider (verified and "
            "active, any of these types). Any other value is 422."
        ),
    ),
) -> list[PublicProviderOut]:

    providers = (
        service.get_public_providers(
            org_type=org_type
        )
    )

    return [
        PublicProviderOut
        .model_validate(provider)
        for provider in providers
    ]


@router.get(
    "/providers/{provider_id}/branches",
    response_model=(
        list[PublicBranchOut]
    ),
)
@blueprint_router.get(
    "/providers/{provider_id}/branches",
    response_model=(
        list[PublicBranchOut]
    ),
)
def list_public_provider_branches(
    provider_id: UUID,
    service: CatalogServiceDependency,
) -> list[PublicBranchOut]:

    branches = (
        service
        .get_public_provider_branches(
            provider_id
        )
    )

    if branches is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail={
                "code":
                    "PUBLIC_PROVIDER_NOT_FOUND",

                "message":
                    (
                        "The selected healthcare "
                        "provider is unavailable."
                    ),
            },
        )

    return [
        PublicBranchOut
        .model_validate(branch)
        for branch in branches
    ]