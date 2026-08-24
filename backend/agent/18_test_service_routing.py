from __future__ import annotations

import asyncio
import json

from medmind.service import (
    MedMindService,
)


# ============================================================
# HELPERS
# ============================================================

def print_result(
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


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    service = await (
        MedMindService.create()
    )

    # ========================================================
    # TEST 1 - BOOKING ROUTE
    # ========================================================

    booking_result = await service.chat(
        session_id=
            "service-routing-book-001",

        message=
            "عايزة احجز",
    )

    print_result(
        "TEST 1 - BOOKING ROUTE",
        booking_result,
    )

    assert (
        booking_result.get(
            "route"
        )
        == "book_appointment"
    )

    booking_state = await (
        service.get_state(
            "service-routing-book-001"
        )
    )

    assert (
        booking_state
        is not None
    )

    assert (
        booking_state.operation_type
        == "book_appointment"
    )

    assert (
        booking_state.stage
        != "new"
    )

    # No booking write should happen yet.
    assert (
        booking_state.appointment_reference
        is None
    )

    print()
    print(
        "BOOKING ROUTE PASSED"
    )

    # ========================================================
    # TEST 2 - CANCEL ROUTE
    # ========================================================

    cancel_result = await service.chat(
        session_id=
            "service-routing-cancel-001",

        message=
            "عايزة ألغي الحجز",
    )

    print_result(
        "TEST 2 - CANCEL ROUTE",
        cancel_result,
    )

    assert (
        cancel_result.get(
            "route"
        )
        == "cancel_appointment"
    )

    cancel_state = await (
        service.get_state(
            "service-routing-cancel-001"
        )
    )

    assert (
        cancel_state
        is not None
    )

    assert (
        cancel_state.operation_type
        == "cancel_appointment"
    )

    assert (
        cancel_state.stage
        in {
            "awaiting_cancel_national_id",
            "awaiting_appointment_reference",
        }
    )

    assert (
        cancel_state.awaiting_confirmation
        is False
    )

    assert (
        cancel_state.pending_action
        is None
    )

    print()
    print(
        "CANCEL ROUTE PASSED"
    )

    # ========================================================
    # TEST 3 - RESCHEDULE ROUTE
    # ========================================================

    reschedule_result = await service.chat(
        session_id=
            "service-routing-reschedule-001",

        message=
            "عايزة أغير ميعاد الحجز",
    )

    print_result(
        "TEST 3 - RESCHEDULE ROUTE",
        reschedule_result,
    )

    assert (
        reschedule_result.get(
            "route"
        )
        == "reschedule_appointment"
    )

    reschedule_state = await (
        service.get_state(
            "service-routing-reschedule-001"
        )
    )

    assert (
        reschedule_state
        is not None
    )

    assert (
        reschedule_state.operation_type
        == "reschedule_appointment"
    )

    assert (
        reschedule_state.stage
        in {
            "awaiting_reschedule_national_id",
            "awaiting_reschedule_reference",
        }
    )

    assert (
        reschedule_state.awaiting_confirmation
        is False
    )

    assert (
        reschedule_state.pending_action
        is None
    )

    print()
    print(
        "RESCHEDULE ROUTE PASSED"
    )

    # ========================================================
    # TEST 4 - READ AGENT FALLBACK
    # ========================================================

    read_result = await service.chat(
        session_id=
            "service-routing-read-001",

        message=
            "إيه التخصصات المتاحة؟",
    )

    print_result(
        "TEST 4 - READ AGENT ROUTE",
        read_result,
    )

    assert (
        read_result.get(
            "route"
        )
        == "read_agent"
    )

    read_state = await (
        service.get_state(
            "service-routing-read-001"
        )
    )

    assert (
        read_state
        is not None
    )

    # Read-only request must not create a write workflow.
    assert (
        read_state.operation_type
        is None
    )

    assert (
        read_state.awaiting_confirmation
        is False
    )

    assert (
        read_state.pending_action
        is None
    )

    print()
    print(
        "READ AGENT ROUTE PASSED"
    )

    # ========================================================
    # TEST 5 - CONTINUE ACTIVE BOOKING WORKFLOW
    # ========================================================

    continuation_session = (
        "service-routing-continuation-001"
    )

    turn_1 = await service.chat(
        session_id=
            continuation_session,

        message=
            "عايزة احجز",
    )

    print_result(
        "TEST 5A - START BOOKING",
        turn_1,
    )

    assert (
        turn_1.get(
            "route"
        )
        == "book_appointment"
    )

    state_after_turn_1 = await (
        service.get_state(
            continuation_session
        )
    )

    assert (
        state_after_turn_1.operation_type
        == "book_appointment"
    )

    # --------------------------------------------------------
    # This second message normally has operation_type=None.
    # Router must continue using state.operation_type.
    # --------------------------------------------------------

    turn_2 = await service.chat(
        session_id=
            continuation_session,

        message=
            "جلدية",
    )

    print_result(
        "TEST 5B - CONTINUE BOOKING",
        turn_2,
    )

    assert (
        turn_2.get(
            "route"
        )
        == "book_appointment"
    )

    state_after_turn_2 = await (
        service.get_state(
            continuation_session
        )
    )

    assert (
        state_after_turn_2.operation_type
        == "book_appointment"
    )

    print()
    print(
        "ACTIVE WORKFLOW CONTINUATION PASSED"
    )

    # ========================================================
    # TEST 6 - EXPLICIT OPERATION SWITCH
    #
    # Start booking then switch to cancellation.
    #
    # This proves current-message operation has priority
    # over old state.operation_type.
    # ========================================================

    switch_session = (
        "service-routing-switch-001"
    )

    switch_turn_1 = await service.chat(
        session_id=
            switch_session,

        message=
            "عايزة احجز",
    )

    print_result(
        "TEST 6A - START BOOKING BEFORE SWITCH",
        switch_turn_1,
    )

    assert (
        switch_turn_1.get(
            "route"
        )
        == "book_appointment"
    )

    switch_state_1 = await (
        service.get_state(
            switch_session
        )
    )

    assert (
        switch_state_1.operation_type
        == "book_appointment"
    )

    # --------------------------------------------------------
    # Explicit new operation.
    # --------------------------------------------------------

    switch_turn_2 = await service.chat(
        session_id=
            switch_session,

        message=
            "لا خلاص عايزة ألغي الحجز",
    )

    print_result(
        "TEST 6B - SWITCH BOOKING TO CANCEL",
        switch_turn_2,
    )

    assert (
        switch_turn_2.get(
            "route"
        )
        == "cancel_appointment"
    )

    switch_state_2 = await (
        service.get_state(
            switch_session
        )
    )

    assert (
        switch_state_2.operation_type
        == "cancel_appointment"
    )

    assert (
        switch_state_2.stage
        in {
            "awaiting_cancel_national_id",
            "awaiting_appointment_reference",
        }
    )

    assert (
        switch_state_2.awaiting_confirmation
        is False
    )

    assert (
        switch_state_2.pending_action
        is None
    )

    print()
    print(
        "EXPLICIT OPERATION SWITCH PASSED"
    )

    # ========================================================
    # FINAL
    # ========================================================

    print()
    print("=" * 70)
    print(
        "MEDMIND SERVICE ROUTING TEST PASSED"
    )
    print("=" * 70)

    print(
        "Booking routed to BookingWorkflow."
    )

    print(
        "Cancellation routed to CancelWorkflow."
    )

    print(
        "Reschedule routed to RescheduleWorkflow."
    )

    print(
        "Read requests routed to MedMindReadAgent."
    )

    print(
        "Active workflows continue across turns."
    )

    print(
        "Explicit new operations override old workflow state."
    )

    print(
        "No write operation was confirmed or executed."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )