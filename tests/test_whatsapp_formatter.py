from datetime import (
    date,
    time,
)

from app.schemas.post_call import (
    WhatsAppBookingNotificationPayload,
)

from app.services.whatsapp_formatter import (
    WhatsAppFormatter,
)


def make_payload(
    *,
    language: str,
):

    return (
        WhatsAppBookingNotificationPayload(
            language=language,

            appointment_reference=
                "APT-260827-ABC123",

            recipient_phone=
                "+201023456789",

            patient_name=
                (
                    "آية أحمد"
                    if language == "ar"
                    else "Aya Ahmed"
                ),

            doctor_name=
                (
                    "دكتور ماهر محمود"
                    if language == "ar"
                    else "Dr. Maher Mahmoud"
                ),

            specialty_name=
                (
                    "جلدية"
                    if language == "ar"
                    else "Dermatology"
                ),

            service_name=
                (
                    "كشف جلدية"
                    if language == "ar"
                    else "Dermatology Consultation"
                ),

            branch_name=
                (
                    "فرع الدقي"
                    if language == "ar"
                    else "Dokki Branch"
                ),

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

            appointment_status=
                "confirmed",

            original_channel=
                "voice",
        )
    )


def test_arabic_booking_message():

    message = (
        WhatsAppFormatter
        .booking_confirmation(
            make_payload(
                language="ar"
            )
        )
    )

    assert (
        "تم تأكيد حجزك"
        in message
    )

    assert (
        "آية أحمد"
        in message
    )

    assert (
        "دكتور ماهر محمود"
        in message
    )

    assert (
        "28/08/2026"
        in message
    )

    assert (
        "5:00 م"
        in message
    )

    assert (
        "APT-260827-ABC123"
        in message
    )


def test_english_booking_message():

    message = (
        WhatsAppFormatter
        .booking_confirmation(
            make_payload(
                language="en"
            )
        )
    )

    assert (
        "Your appointment is confirmed"
        in message
    )

    assert (
        "Aya Ahmed"
        in message
    )

    assert (
        "5:00 PM"
        in message
    )


def test_message_does_not_contain_recipient_phone():

    payload = (
        make_payload(
            language="ar"
        )
    )

    message = (
        WhatsAppFormatter
        .booking_confirmation(
            payload
        )
    )

    assert (
        payload.recipient_phone
        not in message
    )