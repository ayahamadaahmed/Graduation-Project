from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class StaffContext:

    user_id: UUID

    membership_id: UUID

    provider_id: UUID

    role: str

    doctor_id: UUID | None