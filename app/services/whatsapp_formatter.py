from __future__ import annotations

from datetime import (
    date,
    time,
)

from app.schemas.post_call import (
    WhatsAppBookingNotificationPayload,
)


class WhatsAppFormatter:

    @classmethod
    def booking_confirmation(
        cls,
        payload:
            WhatsAppBookingNotificationPayload,
    ) -> str:

        if payload.language == "en":

            return (
                cls
                ._booking_confirmation_en(
                    payload
                )
            )

        return (
            cls
            ._booking_confirmation_ar(
                payload
            )
        )

    # ========================================================
    # Arabic
    # ========================================================

    @classmethod
    def _booking_confirmation_ar(
        cls,
        payload:
            WhatsAppBookingNotificationPayload,
    ) -> str:

        lines = [
            "✅ تم تأكيد حجزك",
            "",
            (
                "👤 المريض: "
                f"{payload.patient_name}"
            ),
        ]

        if payload.doctor_name:

            lines.append(
                "👨‍⚕️ الدكتور: "
                f"{payload.doctor_name}"
            )

        if payload.specialty_name:

            lines.append(
                "🩺 التخصص: "
                f"{payload.specialty_name}"
            )

        if payload.service_name:

            lines.append(
                "📋 الخدمة: "
                f"{payload.service_name}"
            )

        if payload.branch_name:

            lines.append(
                "🏥 الفرع: "
                f"{payload.branch_name}"
            )

        lines.extend(
            [
                (
                    "📅 التاريخ: "
                    + cls._format_date(
                        payload.scheduled_date
                    )
                ),
                (
                    "🕒 الموعد: "
                    + cls._format_time_ar(
                        payload.start_time
                    )
                ),
            ]
        )

        if (
            payload
            .branch_medical_record_number
        ):

            lines.append(
                (
                    "🗂️ رقم الملف بالفرع: "
                    f"{payload.branch_medical_record_number}"
                )
            )

        lines.extend(
            [
                (
                    "🔖 رقم الحجز: "
                    f"{payload.appointment_reference}"
                ),
                "",
                (
                    "احتفظ برقم الحجز "
                    "لاستخدامه عند الحاجة."
                ),
            ]
        )

        return "\n".join(
            lines
        )

    # ========================================================
    # English
    # ========================================================

    @classmethod
    def _booking_confirmation_en(
        cls,
        payload:
            WhatsAppBookingNotificationPayload,
    ) -> str:

        lines = [
            "✅ Your appointment is confirmed",
            "",
            (
                "👤 Patient: "
                f"{payload.patient_name}"
            ),
        ]

        if payload.doctor_name:

            lines.append(
                "👨‍⚕️ Doctor: "
                f"{payload.doctor_name}"
            )

        if payload.specialty_name:

            lines.append(
                "🩺 Specialty: "
                f"{payload.specialty_name}"
            )

        if payload.service_name:

            lines.append(
                "📋 Service: "
                f"{payload.service_name}"
            )

        if payload.branch_name:

            lines.append(
                "🏥 Branch: "
                f"{payload.branch_name}"
            )

        lines.extend(
            [
                (
                    "📅 Date: "
                    + cls._format_date(
                        payload.scheduled_date
                    )
                ),
                (
                    "🕒 Time: "
                    + cls._format_time_en(
                        payload.start_time
                    )
                ),
            ]
        )

        if (
            payload
            .branch_medical_record_number
        ):

            lines.append(
                (
                    "🗂️ Branch MRN: "
                    f"{payload.branch_medical_record_number}"
                )
            )

        lines.extend(
            [
                (
                    "🔖 Booking reference: "
                    f"{payload.appointment_reference}"
                ),
                "",
                (
                    "Keep your booking reference "
                    "for future use."
                ),
            ]
        )

        return "\n".join(
            lines
        )

    # ========================================================
    # Formatting
    # ========================================================

    @staticmethod
    def _format_date(
        value: date,
    ) -> str:

        return (
            f"{value.day:02d}/"
            f"{value.month:02d}/"
            f"{value.year:04d}"
        )

    @staticmethod
    def _format_time_ar(
        value: time,
    ) -> str:

        hour = (
            value.hour % 12
            or 12
        )

        period = (
            "ص"
            if value.hour < 12
            else "م"
        )

        return (
            f"{hour}:"
            f"{value.minute:02d} "
            f"{period}"
        )

    @staticmethod
    def _format_time_en(
        value: time,
    ) -> str:

        hour = (
            value.hour % 12
            or 12
        )

        period = (
            "AM"
            if value.hour < 12
            else "PM"
        )

        return (
            f"{hour}:"
            f"{value.minute:02d} "
            f"{period}"
        )