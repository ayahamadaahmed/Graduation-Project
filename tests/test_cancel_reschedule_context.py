from medmind.state.models import (
    AppointmentSnapshot,
    SessionState,
)

from medmind.workflows.cancel import (
    CancelWorkflow,
)

from medmind.workflows.reschedule import (
    RescheduleWorkflow,
)

from medmind.understanding.types import (
    NLUEntities,
    NLUResult,
)


def make_state(
    **overrides,
):

    values = {
        "channel": "web",
        "session_id": "operation-context-test",
        "tenant_id": "tenant-test",
        "language": "ar",
    }

    values.update(
        overrides
    )

    return SessionState(
        **values
    )


def make_nlu(
    *,
    date_text=None,
    time_text=None,
):

    return NLUResult(
        intent="reschedule_appointment",
        operation_type="reschedule_appointment",
        entities=NLUEntities(
            date_text=date_text,
            time_text=time_text,
        ),
        confirmation="unknown",
        confidence=1.0,
    )


def appointment(
    *,
    reference,
    doctor,
    date,
    time,
):

    return AppointmentSnapshot(
        appointment_reference=reference,
        doctor_name=doctor,
        specialty_name="جلدية",
        service_name="كشف",
        scheduled_date=date,
        start_time=time,
        status="confirmed",
    )


def test_cancel_context_can_identify_one_booking():

    state = make_state(
        pending_operation_entities={
            "doctor_name": "دكتور ماهر",
            "date_text": "2026-09-09",
        }
    )

    appointments = [
        appointment(
            reference="APT-1",
            doctor="دكتور ماهر",
            date="2026-09-09",
            time="14:00",
        ),
        appointment(
            reference="APT-2",
            doctor="دكتور أحمد",
            date="2026-09-09",
            time="14:00",
        ),
    ]

    selected = (
        CancelWorkflow
        ._resolve_contextual_booking(
            state=state,
            appointments=appointments,
        )
    )

    assert selected is not None

    assert (
        selected.appointment_reference
        == "APT-1"
    )


def test_reschedule_uses_doctor_to_identify_current_booking_but_not_new_date():

    state = make_state(
        pending_operation_entities={
            "doctor_name": "دكتور ماهر",
            # This is the NEW requested date, not the old
            # appointment date.
            "date_text": "2026-09-12",
            "time_text": "الساعة 5",
        }
    )

    appointments = [
        appointment(
            reference="APT-1",
            doctor="دكتور ماهر",
            date="2026-09-09",
            time="14:00",
        ),
        appointment(
            reference="APT-2",
            doctor="دكتور أحمد",
            date="2026-09-12",
            time="17:00",
        ),
    ]

    selected = (
        RescheduleWorkflow
        ._resolve_contextual_booking(
            state=state,
            appointments=appointments,
        )
    )

    assert selected is not None

    assert (
        selected.appointment_reference
        == "APT-1"
    )


def test_reschedule_target_date_and_time_survive_identity_turn():

    state = make_state(
        pending_operation_entities={
            "date_text": "بكرة",
            "time_text": "الساعة 5",
        }
    )

    nlu = make_nlu()

    assert (
        RescheduleWorkflow
        ._requested_new_date_text(
            state=state,
            nlu=nlu,
        )
        == "بكرة"
    )

    assert (
        RescheduleWorkflow
        ._requested_new_time_text(
            state=state,
            nlu=nlu,
        )
        == "الساعة 5"
    )
