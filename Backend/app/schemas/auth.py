from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
)

class StaffCurrentResponse(BaseModel):

    user_id: UUID
    membership_id: UUID
    provider_id: UUID
    role: str
    doctor_id: UUID | None = None
    
class StaffLoginRequest(BaseModel):

    email: str = Field(
        ...,
        min_length=1,
        max_length=254,
    )

    password: str = Field(
        ...,
        min_length=1,
        max_length=256,
    )


class StaffLoginResponse(BaseModel):

    access_token: str

    token_type: Literal[
        "bearer"
    ] = "bearer"

    expires_in: int

    user_id: UUID

    membership_id: UUID

    provider_id: UUID

    role: str