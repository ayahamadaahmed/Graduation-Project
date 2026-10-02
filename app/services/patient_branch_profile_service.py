from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status

from app.repositories.patient_branch_profile_repository import (
    PatientBranchProfileRepository,
)


@dataclass(frozen=True, slots=True)
class BranchProfileResult:
    profile_id: UUID
    medical_record_number: str
    created: bool


class PatientBranchProfileService:
    def __init__(
        self,
        repository: PatientBranchProfileRepository,
    ) -> None:
        self.repository = repository

    def resolve(
        self,
        *,
        provider_id: UUID,
        branch_id: UUID,
        patient_id: UUID,
        year: int,
    ) -> BranchProfileResult:

        # Existing patient in this branch.
        existing = (
            self.repository
            .get_existing_profile(
                provider_id=provider_id,
                branch_id=branch_id,
                patient_id=patient_id,
            )
        )

        if existing is not None:
            if not existing["is_active"]:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "BRANCH_PROFILE_INACTIVE"
                        ),
                        "message": (
                            "The patient's branch "
                            "profile is inactive."
                        ),
                    },
                )

            return BranchProfileResult(
                profile_id=UUID(
                    str(existing["id"])
                ),
                medical_record_number=str(
                    existing[
                        "medical_record_number"
                    ]
                ),
                created=False,
            )

        # First visit to this branch.
        branch_code = (
            self.repository.get_branch_code(
                provider_id=provider_id,
                branch_id=branch_id,
            )
        )

        if branch_code is None:
            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail={
                    "code": (
                        "BRANCH_MRN_CODE_MISSING"
                    ),
                    "message": (
                        "This branch does not have "
                        "an MRN code."
                    ),
                },
            )

        branch_code = (
            branch_code.strip().upper()
        )

        if (
            len(branch_code) != 3
            or not branch_code.isascii()
            or not branch_code.isalpha()
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail={
                    "code": (
                        "INVALID_BRANCH_MRN_CODE"
                    ),
                    "message": (
                        "Branch MRN code must be "
                        "exactly 3 letters."
                    ),
                },
            )

        number = self.repository.next_number(
            provider_id=provider_id,
            branch_id=branch_id,
            year=year,
        )

        if number > 999:
            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail={
                    "code": (
                        "BRANCH_MRN_LIMIT_REACHED"
                    ),
                    "message": (
                        "The branch reached the "
                        "annual MRN limit."
                    ),
                },
            )

        mrn = (
            f"{branch_code}-"
            f"{year:04d}-"
            f"{number:03d}"
        )

        profile_id = (
            self.repository.create_profile(
                provider_id=provider_id,
                branch_id=branch_id,
                patient_id=patient_id,
                medical_record_number=mrn,
            )
        )

        return BranchProfileResult(
            profile_id=profile_id,
            medical_record_number=mrn,
            created=True,
        )