from agent.medmind.understanding.context_compressor import (
    compress_understanding_context,
)


def test_compressor_keeps_only_relevant_time_context():

    context = {
        "language": "ar",
        "stage": "awaiting_time",
        "active_capability": "appointment.create",
        "pending_confirmation": False,

        "doctor_id": "doc-123",
        "service_id": "svc-123",
        "slot_id": "slot-123",

        "recent_doctors": [
            {
                "id": "doc-123",
                "full_name_ar": "دكتورة منى",
            }
        ],

        "recent_slots": [
            {
                "id": "slot-123",
                "doctor_id": "doc-123",
                "branch_id": "branch-1",
                "start_time": "17:00:00",
            }
        ],

        "collected_arguments": {
            "specialty_name": "جلدية",
            "doctor_name": "دكتورة منى",
            "date_text": "2026-09-10",
        },

        "offered_doctors": [
            "دكتورة منى",
        ],

        "offered_slots": [
            "17:00",
            "17:30",
        ],
    }

    result = compress_understanding_context(
        context
    )

    assert result == {
        "language": "ar",
        "stage": "awaiting_time",
        "active_capability": "appointment.create",
        "pending_confirmation": False,
        "collected_arguments": {
            "specialty_name": "جلدية",
            "doctor_name": "دكتورة منى",
            "date_text": "2026-09-10",
        },
        "offered_slots": [
            "17:00",
            "17:30",
        ],
    }

    assert "doctor_id" not in result
    assert "service_id" not in result
    assert "slot_id" not in result

    assert "recent_doctors" not in result
    assert "recent_slots" not in result

    # Doctor options are irrelevant while awaiting time.
    assert "offered_doctors" not in result


def test_compressor_keeps_doctors_only_when_awaiting_doctor():

    context = {
        "language": "ar",
        "stage": "awaiting_doctor",
        "active_capability": "appointment.create",
        "pending_confirmation": False,

        "offered_doctors": [
            "دكتور أحمد",
            "دكتورة منى",
        ],

        "offered_services": [
            "كشف",
            "متابعة",
        ],

        "offered_slots": [
            "17:00",
            "17:30",
        ],
    }

    result = compress_understanding_context(
        context
    )

    assert result["offered_doctors"] == [
        "دكتور أحمد",
        "دكتورة منى",
    ]

    assert "offered_services" not in result
    assert "offered_slots" not in result


def test_compressor_keeps_specialties_only_when_awaiting_specialty():

    context = {
        "language": "ar",
        "stage": "awaiting_specialty",
        "active_capability": "appointment.create",
        "pending_confirmation": False,

        "offered_specialties": [
            "جلدية",
            "عيون",
            "أطفال",
        ],
    }

    result = compress_understanding_context(
        context
    )

    assert result["offered_specialties"] == [
        "جلدية",
        "عيون",
        "أطفال",
    ]


def test_compressor_handles_empty_context():

    assert compress_understanding_context(
        None
    ) == {}

    assert compress_understanding_context(
        {}
    ) == {}