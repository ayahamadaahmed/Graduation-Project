from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.repositories.ehr_encounter_repository import (
    EHREncounterRepository,
)
from app.repositories.patient_repository import (
    PatientRepository,
)


class DiagnosticAttachmentBindingError(
    Exception
):
    pass


class DiagnosticPatientNotFoundError(
    DiagnosticAttachmentBindingError
):
    pass


class DiagnosticPatientProviderMismatchError(
    DiagnosticAttachmentBindingError
):
    pass


class DiagnosticEncounterRequiresPatientError(
    DiagnosticAttachmentBindingError
):
    pass


class DiagnosticEncounterNotFoundError(
    DiagnosticAttachmentBindingError
):
    pass


@dataclass(
    frozen=True,
    slots=True,
)
class DiagnosticAttachmentBinding:
    patient_id: UUID | None
    encounter_id: UUID | None


class DiagnosticAttachmentBindingService:

    def __init__(
        self,
        *,
        patient_repository:
            PatientRepository,
        encounter_repository:
            EHREncounterRepository,
    ) -> None:

        self.patient_repository = (
            patient_repository
        )

        self.encounter_repository = (
            encounter_repository
        )

    def resolve(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
    ) -> DiagnosticAttachmentBinding:

        # --------------------------------------------------
        # Unbound attachment remains supported.
        # --------------------------------------------------

        if (
            patient_id is None
            and encounter_id is None
        ):

            return (
                DiagnosticAttachmentBinding(
                    patient_id=None,
                    encounter_id=None,
                )
            )

        # --------------------------------------------------
        # Encounter can never exist without patient context.
        # --------------------------------------------------

        if patient_id is None:

            raise (
                DiagnosticEncounterRequiresPatientError(
                    "patient_id is required when "
                    "encounter_id is provided."
                )
            )

        # --------------------------------------------------
        # Patient must exist and be active globally.
        # --------------------------------------------------

        patient = (
            self.patient_repository
            .get_active_by_id(
                patient_id
            )
        )

        if patient is None:

            raise DiagnosticPatientNotFoundError(
                "The patient was not found "
                "or is inactive."
            )

        # --------------------------------------------------
        # Patient must belong to this provider.
        # --------------------------------------------------

        profile = (
            self.patient_repository
            .get_provider_profile(
                patient_id=patient_id,
                provider_id=provider_id,
            )
        )

        if (
            profile is None
            or not profile.is_active
        ):

            raise (
                DiagnosticPatientProviderMismatchError(
                    "The patient does not have "
                    "an active profile for this "
                    "provider."
                )
            )

        # --------------------------------------------------
        # If encounter exists, it must belong to:
        #
        # same patient
        # + same provider.
        # --------------------------------------------------

        if encounter_id is not None:

            encounter = (
                self.encounter_repository
                .get_for_patient_provider(
                    encounter_id=encounter_id,
                    patient_id=patient_id,
                    provider_id=provider_id,
                )
            )

            if encounter is None:

                raise (
                    DiagnosticEncounterNotFoundError(
                        "The encounter was not found "
                        "for this patient and provider."
                    )
                )

        return DiagnosticAttachmentBinding(
            patient_id=patient_id,
            encounter_id=encounter_id,
        )