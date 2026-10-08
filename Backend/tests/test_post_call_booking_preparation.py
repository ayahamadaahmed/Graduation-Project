from __future__ import annotations

from datetime import (
    date,
    time,
)

from types import (
    SimpleNamespace,
)

from uuid import (
    uuid4,
)

import pytest

from fastapi import (
    HTTPException,
)

from app.services.post_call_service import (
    PostCallService,
)


# ============================================================
# FAKE APPOINTMENT SERVICE
# ============================================================

class FakeAppointmentService:

    def __init__(
        self,
        *,
        appointment=None,
        error=None,
    ) -> None:

        self.appointment = (
            appointment
        )

        self.error = error

        self.calls = []

    def get_booking_by_reference(
        self,
        *,
        provider_id,
        appointment_reference,
    ):

        self.calls.append(
            {
                "provider_id":
                    provider_id,

                "appointment_reference":
                    appointment_reference,
            }
        )

        if self.error is not None:

            raise self.error

        return self.appointment


# ============================================================
# HELPERS
# ============================================================

def make_confirmed_appointment():

    return SimpleNamespace(
        preferred_language=
            "ar",
        appointment_reference=
            "APT-260827-ABC123",

        patient_name=
            "آية أحمد",

        phone=
            "01023456789",

        doctor_name=
            "دكتور ماهر محمود",

        specialty_name=
            "جلدية",

        service_name=
            "كشف جلدية",

        branch_name=
            "فرع الدقي",

        branch_medical_record_number=
            "DOK-2026-001",

        scheduled_date=
            date(
                2026,
                8,
                28,
            ),

        start_time=
            time(
                17,
                0,
            ),

        end_time=
            time(
                17,
                30,
            ),

        status=
            "confirmed",

        channel=
            "voice",
    )


# ============================================================
# TEST 1
# ============================================================

def test_prepare_confirmed_booking_notification():

    appointment = (
        make_confirmed_appointment()
    )

    appointment_service = (
        FakeAppointmentService(
            appointment=
                appointment,
        )
    )

    service = (
        PostCallService(
            appointment_service=
                appointment_service,
        )
    )

    provider_id = (
        uuid4()
    )

    result = (
        service.prepare_booking_confirmation(
            provider_id=
                provider_id,

            appointment_reference=
                "APT-260827-ABC123",
        )
    )

    assert (
        result.event_type
        == "booking_confirmation"
    )

    assert (
        result.destination_channel
        == "whatsapp"
    )

    assert (
        result.appointment_reference
        == "APT-260827-ABC123"
    )

    assert (
        result.recipient_phone
        == "+201023456789"
    )

    assert (
        result.language
        == "ar"
    )

    assert (
        result.patient_name
        == "آية أحمد"
    )

    assert (
        result.doctor_name
        == "دكتور ماهر محمود"
    )

    assert (
        result.service_name
        == "كشف جلدية"
    )

    assert (
        result.branch_name
        == "فرع الدقي"
    )

    assert (
        result.branch_medical_record_number
        == "DOK-2026-001"
    )

    assert (
        result.scheduled_date
        == date(
            2026,
            8,
            28,
        )
    )

    assert (
        result.start_time
        == time(
            17,
            0,
        )
    )

    assert (
        result.original_channel
        == "voice"
    )

    assert (
        appointment_service.calls
        == [
            {
                "provider_id":
                    provider_id,

                "appointment_reference":
                    "APT-260827-ABC123",
            }
        ]
    )


# ============================================================
# TEST 2
# ============================================================

def test_non_confirmed_booking_is_rejected():

    appointment = (
        make_confirmed_appointment()
    )

    appointment.status = (
        "cancelled"
    )

    service = (
        PostCallService(
            appointment_service=
                FakeAppointmentService(
                    appointment=
                        appointment,
                )
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.prepare_booking_confirmation(
            provider_id=
                uuid4(),

            appointment_reference=
                "APT-260827-ABC123",
        )

    assert (
        exc_info.value.status_code
        == 409
    )

    assert (
        exc_info.value.detail[
            "code"
        ]
        == "APPOINTMENT_NOT_CONFIRMED"
    )


# ============================================================
# TEST 3
# ============================================================

def test_invalid_notification_phone_is_rejected():

    appointment = (
        make_confirmed_appointment()
    )

    appointment.phone = (
        "018892"
    )

    service = (
        PostCallService(
            appointment_service=
                FakeAppointmentService(
                    appointment=
                        appointment,
                )
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.prepare_booking_confirmation(
            provider_id=
                uuid4(),

            appointment_reference=
                "APT-260827-ABC123",
        )

    assert (
        exc_info.value.status_code
        == 422
    )

    assert (
        exc_info.value.detail[
            "code"
        ]
        == "INVALID_NOTIFICATION_PHONE"
    )


# ============================================================
# TEST 4
# ============================================================

def test_missing_patient_name_is_rejected():

    appointment = (
        make_confirmed_appointment()
    )

    appointment.patient_name = ""

    service = (
        PostCallService(
            appointment_service=
                FakeAppointmentService(
                    appointment=
                        appointment,
                )
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.prepare_booking_confirmation(
            provider_id=
                uuid4(),

            appointment_reference=
                "APT-260827-ABC123",
        )

    assert (
        exc_info.value.status_code
        == 422
    )

    assert (
        exc_info.value.detail[
            "code"
        ]
        == "PATIENT_NAME_MISSING"
    )