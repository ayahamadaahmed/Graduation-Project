from agent.medmind.service import MedMindService

from agent.medmind.state.models import (
    SessionState,
    SpecialtySnapshot,
    SlotSnapshot,
)


def test_understanding_context_builds_compact_offered_values():

    state = SessionState(
        channel="voice",
        session_id="test-session",
        tenant_id="clinic-001",

        operation_type="book_appointment",
        stage="awaiting_time",

        recent_specialties=[
            SpecialtySnapshot(
                id="spec-1",
                code="DERM",
                name_ar="جلدية",
                name_en="Dermatology",
            ),
            SpecialtySnapshot(
                id="spec-2",
                code="EYE",
                name_ar="عيون",
                name_en="Ophthalmology",
            ),
        ],

        recent_slots=[
            SlotSnapshot(
                id="slot-1",
                doctor_id="doc-1",
                branch_id="branch-1",
                slot_date="2026-09-10",
                start_time="17:00:00",
                end_time="17:30:00",
                status="available",
            ),
            SlotSnapshot(
                id="slot-2",
                doctor_id="doc-1",
                branch_id="branch-1",
                slot_date="2026-09-10",
                start_time="17:30:00",
                end_time="18:00:00",
                status="available",
            ),
        ],
    )

    context = (
        MedMindService._build_understanding_context(
            state
        )
    )

    assert context["offered_specialties"] == [
        "جلدية",
        "عيون",
    ]

    assert context["offered_slots"] == [
        "17:00",
        "17:30",
    ]

    assert (
        context["active_capability"]
        == "appointment.create"
    )