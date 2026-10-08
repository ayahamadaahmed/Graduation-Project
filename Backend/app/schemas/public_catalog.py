from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
)


class PublicProviderOut(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID
    name: str
    slug: str
    org_type: str
    default_language: str


class PublicBranchOut(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID
    provider_id: UUID

    code: str
    name_ar: str
    name_en: str

    address_ar: str | None
    address_en: str | None
    governorate: str | None