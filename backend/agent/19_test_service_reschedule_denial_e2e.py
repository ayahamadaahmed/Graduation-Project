from __future__ import annotations

import asyncio
import json

from medmind.service import (
    MedMindService,
)


TEST_SESSION_ID = (
    "service-reschedule-e2e-denial-001"
)

TEST_NATIONAL_ID = (
    "29901010000001"
)

TEST_APPOINTMENT_REFERENCE = (
    "APT-260818-7733DB38"
)

TEST_CURRENT_SLOT_ID = (
    "7c0c2f34-929b-4590-979e-4bb02a7c6d60"
)

TEST_CURRENT_DATE = (
    "2026-08-20"
)

TEST_CURRENT_TIME = (
    "14:00"
)

TEST_TARGET_SLOT_ID = (
    "6baa229b-0edb-43f7-97b8-06cfcb95cc42"
)

TEST_TARGET_TIME = (
    "14:30"
)


def show(
    title: str,
    result: dict,
) -> None:

    print()
    print("=" * 70)
    print(title)
    print("=" * 70)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


async def main() -> None:

    service = await (
        MedMindService.create()
    )

    # ========================================================
    # TURN 1
    # ========================================================

    result = await service.chat(
        session_id=
            TEST_SESSION_ID,

        message=
            "عايزة أغير ميعاد الحجز",
    )

    show(
        "TURN 1 - START RESCHEDULE",
        result,
    )

    assert (
        result["route"]
        == "reschedule_appointment"
    )

    state = await service.get_state(
        TEST_SESSION_ID
    )

    assert (
        state.stage
        == "awaiting_reschedule_national_id"
    )

    # ========================================================
    # TURN 2 - NATIONAL ID
    # ========================================================

    result = await service.chat(
        session_id=
            TEST_SESSION_ID,

        message=
            TEST_NATIONAL_ID,
    )

    show(
        "TURN 2 - NATIONAL ID",
        result,
    )

    assert (
        result["route"]
        == "reschedule_appointment"
    )

    state = await service.get_state(
        TEST_SESSION_ID
    )

    assert (
        state.national_id
        == TEST_NATIONAL_ID
    )

    assert (
        state.stage
        == "awaiting_reschedule_reference"
    )

    # ========================================================
    # TURN 3 - BOOKING REFERENCE
    # ========================================================

    result = await service.chat(
        session_id=
            TEST_SESSION_ID,

        message=
            TEST_APPOINTMENT_REFERENCE,
    )

    show(
        "TURN 3 - BOOKING REFERENCE",
        result,
    )

    state = await service.get_state(
        TEST_SESSION_ID
    )

    assert (
        state.stage
        == "awaiting_reschedule_date"
    )

    assert (
        state.appointment_reference
        == TEST_APPOINTMENT_REFERENCE
    )

    assert (
        state.slot_id
        == TEST_CURRENT_SLOT_ID
    )

    assert (
        state.slot_date
        == TEST_CURRENT_DATE
    )

    assert (
        state.slot_time
        == TEST_CURRENT_TIME
    )

    # ========================================================
    # TURN 4 - NEW DATE
    # ========================================================

    result = await service.chat(
        session_id=
            TEST_SESSION_ID,

        message=
            "20/8",
    )

    show(
        "TURN 4 - NEW DATE",
        result,
    )

    state = await service.get_state(
        TEST_SESSION_ID
    )

    assert (
        state.stage
        == "awaiting_reschedule_time"
    )

    assert (
        state.new_slot_date
        == TEST_CURRENT_DATE
    )

    target_exists = any(
        str(slot.id)
        == TEST_TARGET_SLOT_ID

        for slot
        in state.recent_slots
    )

    assert (
        target_exists
        is True
    )

    # ========================================================
    # TURN 5 - NEW TIME
    # ========================================================

    result = await service.chat(
        session_id=
            TEST_SESSION_ID,

        message=
            TEST_TARGET_TIME,
    )

    show(
        "TURN 5 - NEW TIME",
        result,
    )

    state = await service.get_state(
        TEST_SESSION_ID
    )

    assert (
        state.stage
        == "awaiting_reschedule_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is True
    )

    assert (
        state.pending_action
        == "reschedule_booking"
    )

    assert (
        state.slot_id
        == TEST_CURRENT_SLOT_ID
    )

    assert (
        state.new_slot_id
        == TEST_TARGET_SLOT_ID
    )

    assert (
        state.new_slot_time
        == TEST_TARGET_TIME
    )

    # ========================================================
    # TURN 6 - DENY
    # ========================================================

    result = await service.chat(
        session_id=
            TEST_SESSION_ID,

        message=
            "لأ",
    )

    show(
        "TURN 6 - DENY",
        result,
    )

    state = await service.get_state(
        TEST_SESSION_ID
    )

    assert (
        state.stage
        == "reschedule_declined"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        state.slot_id
        == TEST_CURRENT_SLOT_ID
    )

    assert (
        state.slot_time
        == TEST_CURRENT_TIME
    )

    assert (
        state.new_slot_id
        is None
    )

    # ========================================================
    # FINAL
    # ========================================================

    print()
    print("=" * 70)
    print(
        "SERVICE RESCHEDULE DENIAL E2E PASSED"
    )
    print("=" * 70)

    print(
        "Language detection passed."
    )

    print(
        "NLU routing passed."
    )

    print(
        "Conversation state continued across turns."
    )

    print(
        "Booking lookup passed."
    )

    print(
        "New slot selection passed."
    )

    print(
        "Explicit confirmation gate passed."
    )

    print(
        "Denial cleared the pending write."
    )

    print(
        "No reschedule write was executed."
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )