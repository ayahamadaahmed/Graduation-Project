from __future__ import annotations

import re
from uuid import UUID

from fastapi import (
    HTTPException,
    status,
)

from app.schemas.post_call import (
    WhatsAppBookingNotificationPayload,
)

from app.services.appointment_service import (
    AppointmentService,
)


ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩",
    "0123456789",
)


class PostCallService:

    def __init__(
        self,
        *,
        appointment_service:
            AppointmentService,
    ) -> None:

        self.appointment_service = (
            appointment_service
        )

    # ========================================================
    # BOOKING CONFIRMATION
    # ========================================================

    def prepare_booking_confirmation(
        self,
        *,
        provider_id: UUID,
        appointment_reference: str,
    ) -> WhatsAppBookingNotificationPayload:

        # ----------------------------------------------------
        # 1. Read the appointment again from trusted DB
        # ----------------------------------------------------

        appointment = (
            self.appointment_service
            .get_booking_by_reference(
                provider_id=
                    provider_id,

                appointment_reference=
                    appointment_reference,
            )
        )

        # ----------------------------------------------------
        # 2. Only confirmed bookings may generate the
        #    booking-confirmation WhatsApp event.
        # ----------------------------------------------------

        if (
            str(
                appointment.status
            ).strip().lower()
            != "confirmed"
        ):

            raise HTTPException(
                status_code=
                    status.HTTP_409_CONFLICT,

                detail={
                    "code":
                        "APPOINTMENT_NOT_CONFIRMED",

                    "message":
                        (
                            "Only a confirmed "
                            "appointment can generate "
                            "a booking confirmation."
                        ),
                },
            )

        # ----------------------------------------------------
        # 3. Validate WhatsApp destination
        # ----------------------------------------------------

        phone = (
            self._normalize_phone(
                appointment.phone
            )
        )

        # ----------------------------------------------------
        # 4. Required patient display name
        # ----------------------------------------------------

        patient_name = (
            appointment.patient_name
            or ""
        ).strip()

        if not patient_name:

            raise HTTPException(
                status_code=
                    status.HTTP_422_UNPROCESSABLE_ENTITY,

                detail={
                    "code":
                        "PATIENT_NAME_MISSING",

                    "message":
                        (
                            "The appointment has no "
                            "patient name available "
                            "for notification."
                        ),
                },
            )


        preferred_language = (
            str(
                getattr(
                    appointment,
                    "preferred_language",
                    "",
                )
                or ""
            )
            .strip()
            .lower()
        )

        language = (
            "en"
            if preferred_language.startswith(
                "en"
            )
            else "ar"
        )
        # ----------------------------------------------------
        # 5. Build trusted internal payload
        # ----------------------------------------------------

        return (
        WhatsAppBookingNotificationPayload(
            language=
                language,

            appointment_reference=(
                appointment
                .appointment_reference
            ),

            recipient_phone=
                phone,

            patient_name=
                patient_name,

            doctor_name=
                appointment.doctor_name,

            specialty_name=
                appointment.specialty_name,

            service_name=
                appointment.service_name,

            branch_name=
                appointment.branch_name,

            branch_medical_record_number=(
                appointment
                .branch_medical_record_number
            ),

            scheduled_date=
                appointment.scheduled_date,

            start_time=
                appointment.start_time,

            end_time=
                appointment.end_time,

            appointment_status=
                appointment.status,

            original_channel=
                appointment.channel,
        )
    )
    # ========================================================
    # PHONE
    # ========================================================
    @staticmethod
    def _normalize_phone(
        value: str,
    ) -> str:

        normalized = (
            str(
                value
                or ""
            )
            .translate(
                ARABIC_DIGITS
            )
            .strip()
            .replace(
                " ",
                "",
            )
            .replace(
                "-",
                "",
            )
            .replace(
                "(",
                "",
            )
            .replace(
                ")",
                "",
            )
        )

        # ========================================================
        # Already Egyptian E.164
        # +2010...
        # ========================================================

        if normalized.startswith(
            "+20"
        ):

            local_number = (
                "0"
                + normalized[
                    3:
                ]
            )

        # ========================================================
        # Local Egyptian format
        # 010...
        # ========================================================

        else:

            local_number = (
                normalized
            )

        if not re.fullmatch(
            r"01[0125]\d{8}",
            local_number,
        ):

            raise HTTPException(
                status_code=
                    status.HTTP_422_UNPROCESSABLE_ENTITY,

                detail={
                    "code":
                        "INVALID_NOTIFICATION_PHONE",

                    "message":
                        (
                            "The appointment does not "
                            "contain a valid Egyptian "
                            "mobile number."
                        ),
                },
            )

        # 01023456789
        #       ↓
        # +201023456789

        return (
            "+20"
            + local_number[
                1:
            ]
        )