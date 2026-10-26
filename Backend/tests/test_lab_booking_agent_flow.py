from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.catalog import SlotOut
from medmind.state.models import SessionState
from medmind.understanding.types import NLUEntities, NLUResult
from medmind.workflows.booking import BookingWorkflow


HELIOPOLIS = {
    "branch_id": "branch-heliopolis",
    "branch_name_ar": "معامل ألفا - مصر الجديدة",
    "branch_name_en": "Alfa Labs - Heliopolis",
}

MAADI = {
    "branch_id": "branch-maadi",
    "branch_name_ar": "معامل ألفا - المعادي",
    "branch_name_en": "Alfa Labs - Maadi",
}


class FakeLabTools:
    """Backend-shaped responses; the real state updater parses them."""

    def __init__(self):
        self.calls = []

    async def call(self, tool_name: str, **kwargs):
        self.calls.append((tool_name, kwargs))

        if tool_name == "list_available_slots":
            slot_date = kwargs["slot_date"]

            def slot(slot_id, branch, start, doctor_id=None):
                return {
                    "id": slot_id,
                    "provider_id": "lab",
                    "doctor_id": doctor_id,
                    "slot_date": slot_date,
                    "start_time": start,
                    "end_time": start,
                    "status": "available",
                    **branch,
                }

            return [
                slot("hel-0900", HELIOPOLIS, "09:00:00"),
                slot("hel-0930", HELIOPOLIS, "09:30:00"),
                slot("maa-0900", MAADI, "09:00:00"),
                slot("maa-0930", MAADI, "09:30:00"),
                # Doctor slot of a lab: never offered in the lab flow.
                slot("doc-1000", MAADI, "10:00:00", doctor_id="doctor-x"),
            ]

        if tool_name == "list_services":
            return [
                {
                    "id": "svc-cbc",
                    "code": "CBC",
                    "name_ar": "صورة دم كاملة",
                    "name_en": "Complete Blood Count",
                    "service_type": "diagnostic",
                    "price": "220.00",
                },
                {
                    "id": "svc-hba1c",
                    "code": "HBA1C",
                    "name_ar": "السكر التراكمي",
                    "name_en": "HbA1c",
                    "service_type": "diagnostic",
                    "price": "300.00",
                },
            ]

        raise AssertionError(f"Unexpected tool: {tool_name}")


def make_nlu(*, intent, operation_type=None, **entities):
    return NLUResult(
        intent=intent,
        operation_type=operation_type,
        entities=NLUEntities(**entities),
        confirmation="unknown",
        confidence=1.0,
    )


def new_state():
    return SessionState(
        channel="web",
        session_id="lab-booking-test",
        tenant_id="lab-001",
        language="ar",
    )


@pytest.mark.asyncio
async def test_lab_booking_flow_without_doctor_with_branch_choice():
    tools = FakeLabTools()
    workflow = BookingWorkflow(tools=tools, provider_type="lab")
    state = new_state()

    # Turn 1: book for tomorrow -> two branches have slots.
    first = await workflow.handle(
        state=state,
        nlu=make_nlu(
            intent="book_appointment",
            operation_type="book_appointment",
            date_text="بكرة",
        ),
        user_message="عايزة أحجز تحليل بكرة",
    )

    assert first.response_type == "ask_branch"
    assert state.stage == "awaiting_branch"
    assert "المعادي" in first.reply and "مصر الجديدة" in first.reply

    slot_call = tools.calls[0]
    assert slot_call[0] == "list_available_slots"
    assert "doctor_id" not in slot_call[1]
    assert all(slot.doctor_id is None for slot in state.recent_slots)
    assert state.doctor_id is None

    # Turn 2: choose the branch by name.
    second = await workflow.handle(
        state=state,
        nlu=make_nlu(intent="ask_provider"),
        user_message="فرع المعادي",
    )

    assert second.response_type == "ask_time"
    assert state.stage == "awaiting_time"
    assert {slot.branch_id for slot in state.recent_slots} == {"branch-maadi"}
    assert second.data["available_times"] == ["09:00", "09:30"]

    # Turn 3: time is now unique (no cross-branch ambiguity).
    third = await workflow.handle(
        state=state,
        nlu=make_nlu(intent="provide_time", time_text="9:30"),
        user_message="9:30",
    )

    assert state.slot_id == "maa-0930"
    services_call = tools.calls[-1]
    assert services_call[0] == "list_services"
    assert services_call[1].get("service_type") == "diagnostic"
    assert "doctor_id" not in services_call[1]
    assert third.response_type != "doctor_required"

    # Turn 4: choose the test.
    fourth = await workflow.handle(
        state=state,
        nlu=make_nlu(intent="provide_service", service_name="صورة دم كاملة"),
        user_message="صورة دم كاملة",
    )

    assert state.service_id == "svc-cbc"
    assert fourth.response_type == "ask_national_id"

    # Patient identity resolved elsewhere; confirmation needs no doctor.
    state.patient_id = "patient-1"
    state.national_id = "29001011234567"
    state.patient_name = "Test Patient"

    confirmation = workflow._prepare_confirmation(state=state)

    assert confirmation.response_type == "booking_confirmation"
    assert "الفرع: معامل ألفا - المعادي" in confirmation.reply
    assert "None" not in confirmation.reply
    assert "الدكتور" not in confirmation.reply


@pytest.mark.asyncio
async def test_lab_unclear_branch_is_asked_again():
    tools = FakeLabTools()
    workflow = BookingWorkflow(tools=tools, provider_type="diagnostic_lab")
    state = new_state()

    await workflow.handle(
        state=state,
        nlu=make_nlu(
            intent="book_appointment",
            operation_type="book_appointment",
            date_text="بكرة",
        ),
        user_message="احجز بكرة",
    )

    # The lab name is shared by both branches -> still ambiguous.
    result = await workflow.handle(
        state=state,
        nlu=make_nlu(intent="ask_provider"),
        user_message="معامل ألفا",
    )

    assert result.response_type == "ask_branch"
    assert state.stage == "awaiting_branch"
    assert len({slot.branch_id for slot in state.recent_slots}) == 2


def test_match_branch_by_number_and_name():
    branches = [
        SimpleNamespace(branch_id="h", **{k: v for k, v in HELIOPOLIS.items() if k != "branch_id"}),
        SimpleNamespace(branch_id="m", **{k: v for k, v in MAADI.items() if k != "branch_id"}),
    ]

    assert BookingWorkflow._match_branch("2", branches).branch_id == "m"
    assert BookingWorkflow._match_branch("١", branches).branch_id == "h"
    assert BookingWorkflow._match_branch("Heliopolis please", branches).branch_id == "h"
    assert BookingWorkflow._match_branch("Alfa Labs", branches) is None
    assert BookingWorkflow._match_branch("3", branches) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [None, "clinic", "hospital"])
async def test_clinic_and_hospital_still_start_with_specialty(provider_type):
    class NoTools:
        async def call(self, tool_name, **kwargs):
            raise AssertionError(f"Unexpected tool: {tool_name}")

    workflow = BookingWorkflow(tools=NoTools(), provider_type=provider_type)
    state = new_state()

    result = await workflow.handle(
        state=state,
        nlu=make_nlu(
            intent="book_appointment",
            operation_type="book_appointment",
        ),
        user_message="عايزة أحجز",
    )

    assert workflow.is_lab is False
    assert result.response_type == "ask_specialty"
    assert state.stage == "awaiting_specialty"


def test_slot_out_carries_branch_names_and_null_doctor():
    slot = SimpleNamespace(
        id=uuid4(),
        provider_id=uuid4(),
        doctor_id=None,
        branch_id=uuid4(),
        slot_date="2026-10-20",
        start_time="09:00:00",
        end_time="09:30:00",
        status="available",
    )
    branch = SimpleNamespace(name_ar="فرع", name_en="Branch")

    item = SlotOut.from_slot(slot, branch)
    assert item.doctor_id is None
    assert item.branch_name_en == "Branch"

    assert SlotOut.from_slot(slot).branch_name_ar is None
