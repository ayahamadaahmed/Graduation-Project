from __future__ import annotations

from medmind.understanding.reference_guard import (
    needs_reference_clarification,
)
from medmind.understanding.tool_planner import (
    ToolPlan,
)


def test_unresolved_arabic_reference_requires_clarification():

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={},
    )

    assert needs_reference_clarification(
        message="عايز أغيره",
        result=result,
        context={},
    ) is True


def test_explicit_reschedule_does_not_require_clarification():

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={
            "date_text": "السبت",
        },
    )

    assert needs_reference_clarification(
        message="عايزة أغير ميعادي للسبت",
        result=result,
        context={},
    ) is False


def test_reference_with_new_argument_can_continue():

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={
            "date_text": "السبت",
        },
    )

    assert needs_reference_clarification(
        message="عايز أغيره للسبت",
        result=result,
        context={},
    ) is False


def test_code_switch_booking_does_not_require_clarification():

    result = ToolPlan(
        status="selected",
        capability="appointment.create",
        arguments={
            "date_text": "بكرة",
        },
    )

    assert needs_reference_clarification(
        message="عايزة book appointment بكرة",
        result=result,
        context={},
    ) is False


def test_active_context_resolves_reference():

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={},
    )

    assert needs_reference_clarification(
        message="عايز أغيره",
        result=result,
        context={
            "active_capability":
                "appointment.reschedule",
            "stage":
                "awaiting_date",
        },
    ) is False


def test_normal_booking_with_empty_arguments_is_not_blocked():

    result = ToolPlan(
        status="selected",
        capability="appointment.create",
        arguments={},
    )

    assert needs_reference_clarification(
        message="عايز أحجز",
        result=result,
        context={},
    ) is False


def test_read_capability_is_never_blocked_by_reference_guard():

    result = ToolPlan(
        status="selected",
        capability="provider.get_services",
        arguments={},
    )

    assert needs_reference_clarification(
        message="عايز أعرف ده",
        result=result,
        context={},
    ) is False


def test_ambiguous_planner_result_is_not_processed_again():

    result = ToolPlan(
        status="ambiguous",
        capability=None,
        arguments={},
        ambiguity_kind="needs_clarification",
    )

    assert needs_reference_clarification(
        message="عايز أغيره",
        result=result,
        context={},
    ) is False