from medmind.service import (
    MedMindService,
)

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.types import (
    NLUEntities,
    NLUResult,
)


def build_service():

    service = object.__new__(
        MedMindService
    )

    service.booking_workflow = object()
    service.cancel_workflow = object()
    service.reschedule_workflow = object()

    return service


def build_reschedule_state():

    return SessionState(
        channel="web",
        session_id="side-question-test",
        tenant_id="clinic-001",
        operation_type=(
            "reschedule_appointment"
        ),
        stage=(
            "awaiting_reschedule_national_id"
        ),
    )


def test_available_slots_question_does_not_get_trapped():

    service = build_service()
    state = build_reschedule_state()

    nlu = NLUResult(
        intent="ask_available_slots",
        operation_type=None,
        confidence=1.0,
        entities=NLUEntities(
            date_text="الخميس",
        ),
    )

    workflow = (
        service._select_workflow(
            state=state,
            nlu=nlu,
        )
    )

    assert workflow is None

    # Active operation must remain untouched.
    assert (
        state.operation_type
        == "reschedule_appointment"
    )

    assert (
        state.stage
        == "awaiting_reschedule_national_id"
    )


def test_doctor_question_does_not_get_trapped():

    service = build_service()
    state = build_reschedule_state()

    nlu = NLUResult(
        intent="ask_doctor",
        operation_type=None,
        confidence=1.0,
        entities=NLUEntities(
            specialty_name="الجلدية",
        ),
    )

    workflow = (
        service._select_workflow(
            state=state,
            nlu=nlu,
        )
    )

    assert workflow is None

    assert (
        state.operation_type
        == "reschedule_appointment"
    )


def test_contextual_date_continues_reschedule():

    service = build_service()
    state = build_reschedule_state()

    nlu = NLUResult(
        intent="provide_date",
        operation_type=None,
        confidence=1.0,
        entities=NLUEntities(
            date_text="الخميس",
        ),
    )

    workflow = (
        service._select_workflow(
            state=state,
            nlu=nlu,
        )
    )

    assert (
        workflow
        is service.reschedule_workflow
    )


def test_national_id_continues_reschedule():

    service = build_service()
    state = build_reschedule_state()

    nlu = NLUResult(
        intent="provide_national_id",
        operation_type=None,
        confidence=1.0,
        entities=NLUEntities(
            national_id="29801011234567",
        ),
    )

    workflow = (
        service._select_workflow(
            state=state,
            nlu=nlu,
        )
    )

    assert (
        workflow
        is service.reschedule_workflow
    )


def test_explicit_booking_switches_from_reschedule():

    service = build_service()
    state = build_reschedule_state()

    nlu = NLUResult(
        intent="book_appointment",
        operation_type="book_appointment",
        confidence=1.0,
        entities=NLUEntities(),
    )

    workflow = (
        service._select_workflow(
            state=state,
            nlu=nlu,
        )
    )

    assert (
        workflow
        is service.booking_workflow
    )