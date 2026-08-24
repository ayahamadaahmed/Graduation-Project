import re
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.patient_identity import (
    PatientIdentityProtector,
)
from app.repositories.patient_repository import (
    PatientRepository,
)
from app.schemas.patient import (
    PatientLookupResult,
    PatientRead,
    PatientResolution,
)


_DIGIT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)

_EGYPTIAN_MOBILE_PATTERN = re.compile(
    r"01[0125]\d{8}\Z"
)


class PatientService:
    def __init__(
        self,
        repository: PatientRepository,
        identity_protector: (
            PatientIdentityProtector
        ),
    ) -> None:
        self.repository = repository
        self.identity_protector = (
            identity_protector
        )

    def resolve_for_booking(
        self,
        *,
        provider_id: UUID,
        provider_timezone: str,
        national_id: str,
        patient_name: str,
        phone: str,
        preferred_language: str,
        channel: str,
    ) -> PatientResolution:
        name = self._normalize_name(
            patient_name
        )

        normalized_phone = (
            self._normalize_phone(phone)
        )

        try:
            protected_id = (
                self.identity_protector
                .protect(national_id)
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code": "INVALID_NATIONAL_ID",
                    "message": str(exc),
                },
            ) from exc

        patient = (
            self.repository
            .get_by_national_id_hash(
                protected_id.hash_value
            )
        )

        patient_created = False
        profile_created = False

        try:
            if patient is None:
                year = datetime.now(
                    ZoneInfo(provider_timezone)
                ).year

                patient_code = (
                    self.repository
                    .generate_patient_code(year)
                )

                full_name_en = (
                    name
                    if preferred_language == "en"
                    else None
                )

                patient = (
                    self.repository.create_patient(
                        patient_code=patient_code,
                        national_id_hash=(
                            protected_id.hash_value
                        ),
                        national_id_encrypted=(
                            protected_id
                            .encrypted_value
                        ),
                        national_id_last4=(
                            protected_id.last4
                        ),
                        full_name_ar=name,
                        full_name_en=full_name_en,
                        phone=normalized_phone,
                        preferred_language=(
                            preferred_language
                        ),
                    )
                )

                patient_created = True

            elif not patient.is_active:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": "PATIENT_INACTIVE",
                        "message": (
                            "The patient account "
                            "is inactive."
                        ),
                    },
                )

            profile = (
                self.repository
                .get_provider_profile(
                    patient_id=patient.id,
                    provider_id=provider_id,
                )
            )

            if profile is None:
                profile = (
                    self.repository
                    .create_provider_profile(
                        patient_id=patient.id,
                        provider_id=provider_id,
                        preferred_channel=channel,
                    )
                )

                profile_created = True

            self.repository.session.commit()

            self.repository.session.refresh(
                patient
            )

            self.repository.session.refresh(
                profile
            )

        except IntegrityError:
            self.repository.session.rollback()

            # Another request may have created
            # the same patient concurrently.
            patient = (
                self.repository
                .get_by_national_id_hash(
                    protected_id.hash_value
                )
            )

            if patient is None:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "PATIENT_CREATE_CONFLICT"
                        ),
                        "message": (
                            "Patient creation "
                            "conflicted with another "
                            "request."
                        ),
                    },
                )

            profile = (
                self.repository
                .get_provider_profile(
                    patient_id=patient.id,
                    provider_id=provider_id,
                )
            )

            if profile is None:
                try:
                    profile = (
                        self.repository
                        .create_provider_profile(
                            patient_id=patient.id,
                            provider_id=provider_id,
                            preferred_channel=(
                                channel
                            ),
                        )
                    )

                    self.repository.session.commit()

                    self.repository.session.refresh(
                        profile
                    )

                    profile_created = True

                except IntegrityError:
                    self.repository.session.rollback()

                    profile = (
                        self.repository
                        .get_provider_profile(
                            patient_id=patient.id,
                            provider_id=provider_id,
                        )
                    )

                    if profile is None:
                        raise HTTPException(
                            status_code=(
                                status
                                .HTTP_409_CONFLICT
                            ),
                            detail={
                                "code": (
                                    "PROFILE_CREATE_"
                                    "CONFLICT"
                                ),
                                "message": (
                                    "Provider profile "
                                    "could not be created."
                                ),
                            },
                        )

            patient_created = False

        return PatientResolution(
            patient=PatientRead.model_validate(
                patient
            ),
            provider_profile_id=profile.id,
            patient_created=patient_created,
            provider_profile_created=(
                profile_created
            ),
        )

    def lookup(
        self,
        *,
        national_id: str,
        language: str,
    ) -> PatientLookupResult | None:
        try:
            national_id_hash = (
                self.identity_protector
                .hash_national_id(national_id)
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code": "INVALID_NATIONAL_ID",
                    "message": str(exc),
                },
            ) from exc

        patient = (
            self.repository
            .get_active_by_national_id_hash(
                national_id_hash
            )
        )

        if patient is None:
            return None

        display_name = (
            patient.full_name_en
            if (
                language == "en"
                and patient.full_name_en
            )
            else patient.full_name_ar
        )

        return PatientLookupResult(
            patient_id=patient.id,
            patient_code=patient.patient_code,
            display_name=display_name,
            masked_national_id=(
                patient.masked_national_id
            ),
            phone=patient.phone,
        )

    @staticmethod
    def _normalize_name(
        value: str,
    ) -> str:
        normalized = " ".join(
            value.strip().split()
        )

        if len(normalized) < 2:
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code": "INVALID_PATIENT_NAME",
                    "message": (
                        "Patient name is too short."
                    ),
                },
            )

        return normalized

    @staticmethod
    def _normalize_phone(
        value: str,
    ) -> str:

        translated = (
            value.strip()
            .translate(
                _DIGIT_TRANSLATION
            )
        )

        normalized = re.sub(
            r"[\s()\-]",
            "",
            translated,
        )

        # International Egyptian format:
        # +201012345678 -> 01012345678
        if normalized.startswith(
            "+20"
        ):
            normalized = (
                "0"
                + normalized[3:]
            )

        # 201012345678 -> 01012345678
        elif normalized.startswith(
            "20"
        ):
            normalized = (
                "0"
                + normalized[2:]
            )

        if not (
            _EGYPTIAN_MOBILE_PATTERN
            .fullmatch(
                normalized
            )
        ):
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code":
                        "INVALID_PHONE",

                    "message": (
                        "Egyptian mobile number must contain "
                        "11 digits and start with 010, 011, "
                        "012, or 015."
                    ),
                },
            )

        return normalized