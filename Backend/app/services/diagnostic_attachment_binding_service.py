from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.patient_identity import (
    PatientIdentityProtector,
)
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


class DiagnosticNationalIdRequiredError(
    DiagnosticAttachmentBindingError
):
    """Binding a patient requires the patient's national ID."""


class DiagnosticInvalidNationalIdError(
    DiagnosticAttachmentBindingError
):
    """The supplied national ID is malformed."""


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
        identity_protector_factory: (
            Callable[[], PatientIdentityProtector] | None
        ) = None,
    ) -> None:

        self.patient_repository = (
            patient_repository
        )

        self.encounter_repository = (
            encounter_repository
        )

        # Built lazily: unbound uploads must work even without identity keys.
        self.identity_protector_factory = (
            identity_protector_factory
        )

    def resolve(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
        national_id: str | None = None,
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
        # Identity: binding a patient needs proof that the
        # caller knows that patient's national ID. A mismatch
        # answers exactly like an unknown patient. The value
        # is only hashed here; it is never stored or logged.
        # --------------------------------------------------

        self._verify_identity(
            patient_id=patient_id,
            national_id=national_id,
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

    def _verify_identity(
        self,
        *,
        patient_id: UUID,
        national_id: str | None,
    ) -> None:
        if national_id is None or not national_id.strip():
            raise DiagnosticNationalIdRequiredError(
                "national_id is required when "
                "patient_id is provided."
            )

        if self.identity_protector_factory is None:
            raise RuntimeError(
                "Patient identity verification "
                "is not configured."
            )

        try:
            national_id_hash = (
                self.identity_protector_factory()
                .hash_national_id(national_id)
            )
        except ValueError as exc:
            raise DiagnosticInvalidNationalIdError(
                "National ID must contain exactly 14 digits."
            ) from exc

        identified = (
            self.patient_repository
            .get_active_by_national_id_hash(
                national_id_hash
            )
        )

        if (
            identified is None
            or identified.id != patient_id
        ):
            raise DiagnosticPatientNotFoundError(
                "The patient was not found "
                "or is inactive."
            )
