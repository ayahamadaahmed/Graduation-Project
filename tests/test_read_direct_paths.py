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

        if tool_name == "list_specialties":

            return [
                {
                    "id": "specialty-derma",
                    "code": "DERMA",
                    "name_ar": "جلدية",
                    "name_en": "Dermatology",
                }
            ]

        if tool_name == "list_doctors":

            return [
                {
                    "id": "doctor-ahmed",
                    "specialty_id": "specialty-derma",
                    "full_name_ar": "دكتور أحمد",
                    "full_name_en": "Dr Ahmed",
                    "specialty_name_ar": "جلدية",
                    "specialty_name_en": "Dermatology",
                    "consultation_fee": "500",
                    "experience_years": 10,
                },
                {
                    "id": "doctor-mahmoud",
                    "specialty_id": "specialty-derma",
                    "full_name_ar": "دكتور محمود",
                    "full_name_en": "Dr Mahmoud",
                    "specialty_name_ar": "جلدية",
                    "specialty_name_en": "Dermatology",
                    "consultation_fee": "450",
                    "experience_years": 8,
                },
            ]

        if tool_name == "list_services":

            assert (
                kwargs.get(
                    "doctor_id"
                )
                == "doctor-ahmed"
            )

            return [
                {
                    "id": "service-exam",
                    "code": "EXAM",
                    "name_ar": "كشف",
                    "name_en": "Examination",
                    "price": "500",
                    "service_type": "consultation",
                }
            ]

        raise AssertionError(
            f"Unexpected tool: {tool_name}"
        )


def fake_apply_tool_observation(
    *,
    state,
    tool_name,
    data,
):

    if tool_name == "list_specialties":

        state.recent_specialties = [
            SimpleNamespace(
                id=item["id"],
                code=item["code"],
                name_ar=item["name_ar"],
                name_en=item["name_en"],
            )
            for item in data
        ]

    elif tool_name == "list_doctors":

        state.recent_doctors = [
            SimpleNamespace(
                id=item["id"],
                specialty_id=item["specialty_id"],
                full_name_ar=item["full_name_ar"],
                full_name_en=item["full_name_en"],
                specialty_name_ar=item[
                    "specialty_name_ar"
                ],
                specialty_name_en=item[
                    "specialty_name_en"
                ],
                consultation_fee=item.get(
                    "consultation_fee"
                ),
                experience_years=item.get(
                    "experience_years"
                ),
                rating_avg=None,
                review_count=None,
            )
            for item in data
        ]

    elif tool_name == "list_services":

        state.recent_services = [
            SimpleNamespace(
                id=item["id"],
                code=item["code"],
                name_ar=item["name_ar"],
                name_en=item["name_en"],
                price=item.get(
                    "price"
                ),
                service_type=item.get(
                    "service_type"
                ),
            )
            for item in data
        ]


def make_state(
    **overrides,
):

    values = {
        "channel": "web",
        "session_id": "read-direct-test",
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
    intent,
    specialty_name=None,
    doctor_name=None,
    service_name=None,
):

    return NLUResult(
        intent=intent,
        operation_type=None,
        entities=NLUEntities(
            specialty_name=specialty_name,
            doctor_name=doctor_name,
            service_name=service_name,
        ),
        confirmation="unknown",
        confidence=1.0,
    )


def make_service(
    tools,
):

    return MedMindService(
        tenant_id="tenant-test",
        agent=object(),
        nlu=object(),
        understanding=object(),
        booking_workflow=object(),
        cancel_workflow=object(),
        reschedule_workflow=object(),
        state_store=object(),
        memory=object(),
        tools=tools,
    )


@pytest.mark.asyncio
async def test_doctor_read_lists_specialty_doctors_without_read_agent(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    service = make_service(
        tools
    )

    state = make_state()

    nlu = make_nlu(
        intent="ask_doctor",
        specialty_name="جلدية",
    )

    (
        reply,
        response_type,
    ) = await service._handle_doctor_read(
        state=state,
        nlu=nlu,
        language="ar",
        channel="web",
    )

    assert (
        response_type
        == "doctor_list"
    )

    assert "دكتور أحمد" in reply
    assert "دكتور محمود" in reply

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert [
        name
        for name, _
        in tools.calls
    ] == [
        "list_specialties",
        "list_doctors",
    ]


@pytest.mark.asyncio
async def test_service_read_resolves_doctor_and_lists_services(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    service = make_service(
        tools
    )

    state = make_state()

    nlu = make_nlu(
        intent="ask_service",
        doctor_name="أحمد",
    )

    (
        reply,
        response_type,
    ) = await service._handle_service_read(
        state=state,
        nlu=nlu,
        language="ar",
        channel="web",
    )

    assert (
        response_type
        == "service_list"
    )

    assert "كشف" in reply

    assert (
        state.doctor_id
        == "doctor-ahmed"
    )

    assert (
        state.conversation_doctor_id
        == "doctor-ahmed"
    )

    assert [
        name
        for name, _
        in tools.calls
    ] == [
        "list_doctors",
        "list_services",
    ]


@pytest.mark.asyncio
async def test_service_details_preserve_trusted_service_context(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    service = make_service(
        tools
    )

    state = make_state(
        conversation_specialty_id=
            "specialty-derma",
        conversation_specialty_name=
            "جلدية",
        conversation_doctor_id=
            "doctor-ahmed",
        conversation_doctor_name=
            "دكتور أحمد",
    )

    nlu = make_nlu(
        intent="ask_service",
        service_name="كشف",
    )

    (
        reply,
        response_type,
    ) = await service._handle_service_read(
        state=state,
        nlu=nlu,
        language="ar",
        channel="web",
    )

    assert (
        response_type
        == "service_details"
    )

    assert "500" in reply

    assert (
        state.service_id
        == "service-exam"
    )

    assert (
        state.conversation_service_id
        == "service-exam"
    )


@pytest.mark.asyncio
async def test_current_doctor_overrides_old_cross_specialty_context(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    service = make_service(
        tools
    )

    state = make_state(
        conversation_specialty_id=
            "specialty-cardio",
        conversation_specialty_name=
            "قلب",
        conversation_doctor_id=
            "doctor-old",
        conversation_doctor_name=
            "دكتور قديم",
    )

    nlu = make_nlu(
        intent="ask_doctor",
        doctor_name="دكتور محمود",
    )

    (
        reply,
        response_type,
    ) = await service._handle_doctor_read(
        state=state,
        nlu=nlu,
        language="ar",
        channel="web",
    )

    assert (
        response_type
        == "doctor_details"
    )

    assert (
        state.doctor_id
        == "doctor-mahmoud"
    )

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert "دكتور محمود" in reply

    # Critical: the new doctor was resolved broadly, not
    # constrained by the stale cardiology specialty.
    assert (
        tools.calls[0][0]
        == "list_doctors"
    )

    assert (
        "specialty_id"
        not in tools.calls[0][1]
    )

class SpecialtyServiceTools(FakeTools):

    async def call(
        self,
        tool_name: str,
        **kwargs,
    ):

        if tool_name == "list_services":

            self.calls.append(
                (
                    tool_name,
                    kwargs,
                )
            )

            assert (
                kwargs.get("specialty_id")
                == "specialty-derma"
            )

            assert "doctor_id" not in kwargs

            return [
                {
                    "id": "service-exam",
                    "code": "EXAM",
                    "name_ar": "كشف",
                    "name_en": "Examination",
                    "price": "500",
                    "service_type": "consultation",
                }
            ]

        return await super().call(
            tool_name,
            **kwargs,
        )


@pytest.mark.asyncio
async def test_service_read_lists_specialty_services_without_doctor_lookup(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.service.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = SpecialtyServiceTools()

    service = make_service(
        tools
    )

    state = make_state(
        language="en",
    )

    nlu = make_nlu(
        intent="ask_service",
        specialty_name="Dermatology",
    )

    (
        reply,
        response_type,
    ) = await service._handle_service_read(
        state=state,
        nlu=nlu,
        language="en",
        channel="web",
    )

    assert response_type == "service_list"

    assert "Examination" in reply

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert [
        name
        for name, _
        in tools.calls
    ] == [
        "list_specialties",
        "list_services",
    ]

    assert (
        tools.calls[-1][1]["specialty_id"]
        == "specialty-derma"
    )