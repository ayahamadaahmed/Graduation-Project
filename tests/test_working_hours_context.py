from types import SimpleNamespace

import pytest

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


# ============================================================
# FAKE TOOLS
# ============================================================

class FakeTools:

    def __init__(self):

        self.calls = []

    async def call(
        self,
        tool_name: str,
        **kwargs,
    ):

        self.calls.append(
            (
                tool_name,
                kwargs,
            )
        )

        # ====================================================
        # PROVIDER DOCTORS
        # ====================================================

        if tool_name == "list_doctors":

            return [
                {
                    "id":
                        "doctor-ahmed",

                    "full_name_ar":
                        "دكتور أحمد",

                    "full_name_en":
                        "Dr Ahmed",
                },
                {
                    "id":
                        "doctor-mahmoud",

                    "full_name_ar":
                        "دكتور محمود",

                    "full_name_en":
                        "Dr Mahmoud",
                },
            ]

        # ====================================================
        # WORKING HOURS
        #
        # Return one schedule for every weekday so tests that
        # use "بكرة" work regardless of the current date.
        # ====================================================

        if tool_name == "get_working_hours":

            return [
                {
                    "day_of_week":
                        day,

                    "start_time":
                        "12:00:00",

                    "end_time":
                        "15:00:00",
                }
                for day in range(7)
            ]

        raise AssertionError(
            f"Unexpected tool call: {tool_name}"
        )


# ============================================================
# FAKE APPLY TOOL OBSERVATION
# ============================================================

def fake_apply_tool_observation(
    *,
    state,
    tool_name,
    data,
):

    if tool_name == "list_doctors":

        state.recent_doctors = [
            SimpleNamespace(
                id=item["id"],

                full_name_ar=
                    item["full_name_ar"],

                full_name_en=
                    item["full_name_en"],
            )
            for item in data
        ]


# ============================================================
# HELPERS
# ============================================================

def make_state(
    **overrides,
):

    values = {
        "channel":
            "web",

        "session_id":
            "working-hours-test",

        "tenant_id":
            "tenant-test",

        "language":
            "ar",
    }

    values.update(
        overrides
    )

    return SessionState(
        **values
    )


def make_nlu(
    *,
    doctor_name=None,
    specialty_name=None,
    date_text=None,
):

    return NLUResult(
        intent=
            "ask_working_hours",

        operation_type=
            None,

        entities=NLUEntities(
            doctor_name=
                doctor_name,

            specialty_name=
                specialty_name,

            date_text=
                date_text,
        ),

        confirmation=
            "unknown",

        confidence=
            1.0,
    )


def make_service(
    tools,
):

    return MedMindService(
        tenant_id=
            "tenant-test",

        agent=
            object(),

        nlu=
            object(),

        understanding=
            object(),

        booking_workflow=
            object(),

        cancel_workflow=
            object(),

        reschedule_workflow=
            object(),

        state_store=
            object(),

        memory=
            object(),

        tools=
            tools,
    )


# ============================================================
# 1. NO DOCTOR CONTEXT
# ============================================================

@pytest.mark.asyncio
async def test_working_hours_without_doctor_asks_for_doctor():

    tools = FakeTools()

    service = (
        make_service(
            tools
        )
    )

    state = (
        make_state()
    )

    nlu = (
        make_nlu()
    )

    (
        reply,
        response_type,
    ) = await (
        service
        ._handle_working_hours_read(
            state=state,
            nlu=nlu,
            language="ar",
        )
    )

    assert (
        response_type
        == "ask_working_hours_doctor"
    )

    assert (
        "دكتور"
        in reply
    )

    # Critical:
    # do NOT query every doctor's schedule.
    assert (
        tools.calls
        == []
    )


# ============================================================
# 2. EXPLICIT DOCTOR NAME
#
# "مواعيد دكتور أحمد؟"
#
# Name must be resolved to trusted DB ID first.
# ============================================================

@pytest.mark.asyncio
async def test_working_hours_resolves_explicit_doctor_name(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    service = (
        make_service(
            tools
        )
    )

    state = (
        make_state()
    )

    nlu = (
        make_nlu(
            doctor_name=
                "دكتور أحمد",
        )
    )

    (
        reply,
        response_type,
    ) = await (
        service
        ._handle_working_hours_read(
            state=state,
            nlu=nlu,
            language="ar",
        )
    )

    assert (
        response_type
        == "working_hours"
    )

    # ========================================================
    # TRUSTED DOCTOR STATE
    # ========================================================

    assert (
        state.doctor_id
        == "doctor-ahmed"
    )

    assert (
        state.doctor_name
        == "دكتور أحمد"
    )

    # ========================================================
    # EXPECTED TOOL CHAIN
    # ========================================================

    assert (
        tools.calls[0][0]
        == "list_doctors"
    )

    assert (
        tools.calls[1][0]
        == "get_working_hours"
    )

    assert (
        tools.calls[1][1][
            "doctor_id"
        ]
        == "doctor-ahmed"
    )

    assert (
        "دكتور أحمد"
        in reply
    )


# ============================================================
# 3. FOLLOW-UP DATE USES PREVIOUS DOCTOR
#
# Previous:
# "مواعيد دكتور أحمد؟"
#
# Current:
# "طب بكرة؟"
#
# Must NOT ask for doctor again.
# Must NOT call list_doctors again when trusted doctor ID
# already exists in conversation context.
# ============================================================

@pytest.mark.asyncio
async def test_working_hours_followup_date_uses_conversation_doctor():

    tools = FakeTools()

    service = (
        make_service(
            tools
        )
    )

    state = (
        make_state(
            conversation_doctor_name=
                "دكتور أحمد",

            conversation_doctor_id=
                "doctor-ahmed",

            conversation_focus_capability=
                "provider.get_working_hours",
        )
    )

    nlu = (
        make_nlu(
            date_text=
                "بكرة",
        )
    )

    (
        reply,
        response_type,
    ) = await (
        service
        ._handle_working_hours_read(
            state=state,
            nlu=nlu,
            language="ar",
        )
    )

    assert (
        response_type
        == "working_hours"
    )

    # ========================================================
    # DIRECT TRUSTED LOOKUP
    # ========================================================

    assert (
        len(
            tools.calls
        )
        == 1
    )

    assert (
        tools.calls[0][0]
        == "get_working_hours"
    )

    assert (
        tools.calls[0][1][
            "doctor_id"
        ]
        == "doctor-ahmed"
    )

    # Should answer the requested date, not ask for doctor.
    assert (
        "دكتور أحمد"
        in reply
    )

    assert (
        "مواعيد أنهي دكتور"
        not in reply
    )

@pytest.mark.asyncio
async def test_working_hours_current_doctor_overrides_previous_doctor(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    service = (
        make_service(
            tools
        )
    )

    # ========================================================
    # OLD CONVERSATION
    #
    # Previous question was about Ahmed.
    # ========================================================

    state = (
        make_state(
            conversation_doctor_name=
                "دكتور أحمد",

            conversation_doctor_id=
                "doctor-ahmed",

            conversation_focus_capability=
                "provider.get_working_hours",
        )
    )

    # ========================================================
    # CURRENT TURN
    #
    # "طب دكتور محمود؟"
    #
    # Current turn MUST override previous doctor.
    # ========================================================

    nlu = (
        make_nlu(
            doctor_name=
                "دكتور محمود",
        )
    )

    (
        reply,
        response_type,
    ) = await (
        service
        ._handle_working_hours_read(
            state=state,
            nlu=nlu,
            language="ar",
        )
    )

    assert (
        response_type
        == "working_hours"
    )

    # ========================================================
    # CURRENT DOCTOR MUST WIN
    # ========================================================

    assert (
        state.doctor_id
        == "doctor-mahmoud"
    )

    assert (
        state.doctor_name
        == "دكتور محمود"
    )

    # ========================================================
    # NEW NAME MUST BE RESOLVED AGAIN
    #
    # We must NOT reuse Ahmed's old database ID.
    # ========================================================

    assert (
        tools.calls[0][0]
        == "list_doctors"
    )

    assert (
        tools.calls[1][0]
        == "get_working_hours"
    )

    assert (
        tools.calls[1][1][
            "doctor_id"
        ]
        == "doctor-mahmoud"
    )

    assert (
        "دكتور محمود"
        in reply
    )


# ============================================================
# SPECIALTY-AWARE FAKE TOOLS
# ============================================================

class SpecialtyFakeTools:

    def __init__(
        self,
        *,
        doctors,
    ):

        self.calls = []
        self.doctors = doctors

    async def call(
        self,
        tool_name: str,
        **kwargs,
    ):

        self.calls.append(
            (
                tool_name,
                kwargs,
            )
        )

        if tool_name == "list_specialties":

            return [
                {
                    "id":
                        "specialty-derma",

                    "name_ar":
                        "جلدية",

                    "name_en":
                        "Dermatology",

                    "code":
                        "DERMA",
                }
            ]

        if tool_name == "list_doctors":

            assert (
                kwargs.get(
                    "specialty_id"
                )
                == "specialty-derma"
            )

            return (
                self.doctors
            )

        if tool_name == "get_working_hours":

            return [
                {
                    "day_of_week":
                        day,

                    "start_time":
                        "12:00:00",

                    "end_time":
                        "15:00:00",
                }
                for day in range(7)
            ]

        raise AssertionError(
            f"Unexpected tool call: {tool_name}"
        )


@pytest.mark.asyncio
async def test_working_hours_specialty_with_multiple_doctors_asks_for_doctor(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = SpecialtyFakeTools(
        doctors=[
            {
                "id":
                    "doctor-ahmed",

                "full_name_ar":
                    "دكتور أحمد",

                "full_name_en":
                    "Dr Ahmed",
            },
            {
                "id":
                    "doctor-mahmoud",

                "full_name_ar":
                    "دكتور محمود",

                "full_name_en":
                    "Dr Mahmoud",
            },
        ]
    )

    service = (
        make_service(
            tools
        )
    )

    state = (
        make_state()
    )

    nlu = (
        make_nlu(
            specialty_name=
                "جلدية",
        )
    )

    (
        reply,
        response_type,
    ) = await (
        service
        ._handle_working_hours_read(
            state=state,
            nlu=nlu,
            language="ar",
        )
    )

    # ========================================================
    # SPECIALTY RESOLVED
    # ========================================================

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert (
        state.specialty_name
        == "جلدية"
    )

    # ========================================================
    # MULTIPLE DOCTORS → ASK ONLY FOR DOCTOR
    # ========================================================

    assert (
        response_type
        == "ask_working_hours_doctor"
    )

    assert (
        "دكتور أحمد"
        in reply
    )

    assert (
        "دكتور محمود"
        in reply
    )

    # Do not choose a doctor silently.
    assert (
        state.doctor_id
        is None
    )

    assert (
        state.doctor_name
        is None
    )

    # ========================================================
    # TOOL CHAIN
    # ========================================================

    tool_names = [
        name
        for name, _
        in tools.calls
    ]

    assert tool_names == [
        "list_specialties",
        "list_doctors",
    ]

    # Critical:
    # working hours must NOT be queried before doctor choice.
    assert (
        "get_working_hours"
        not in tool_names
    )


@pytest.mark.asyncio
async def test_working_hours_specialty_with_one_doctor_continues_automatically(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = SpecialtyFakeTools(
        doctors=[
            {
                "id":
                    "doctor-mona",

                "full_name_ar":
                    "دكتور منى",

                "full_name_en":
                    "Dr Mona",
            }
        ]
    )

    service = (
        make_service(
            tools
        )
    )

    state = (
        make_state()
    )

    nlu = (
        make_nlu(
            specialty_name=
                "جلدية",
        )
    )

    (
        reply,
        response_type,
    ) = await (
        service
        ._handle_working_hours_read(
            state=state,
            nlu=nlu,
            language="ar",
        )
    )

    # ========================================================
    # SPECIALTY
    # ========================================================

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert (
        state.specialty_name
        == "جلدية"
    )

    # ========================================================
    # ONLY ONE DOCTOR → AUTO SELECT
    # ========================================================

    assert (
        state.doctor_id
        == "doctor-mona"
    )

    assert (
        state.doctor_name
        == "دكتور منى"
    )

    # ========================================================
    # SHOULD RETURN WORKING HOURS DIRECTLY
    # ========================================================

    assert (
        response_type
        == "working_hours"
    )

    assert (
        "دكتور منى"
        in reply
    )

    # ========================================================
    # TOOL CHAIN
    # ========================================================

    tool_names = [
        name
        for name, _
        in tools.calls
    ]

    assert tool_names == [
        "list_specialties",
        "list_doctors",
        "get_working_hours",
    ]

    assert (
        tools.calls[-1][1][
            "doctor_id"
        ]
        == "doctor-mona"
    )                