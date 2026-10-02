from agent.medmind.understanding.tool_plan_validator import (
    ToolPlanValidator,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)


def test_accepts_matching_contextual_capability():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.create",
        arguments={
            "specialty_name": "جلدية",
        },
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="جلدية",
        result=result,
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_specialty",
        },
    )

    assert validation.valid is True
    assert validation.reason == ""


def test_rejects_unrelated_contextual_capability():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.cancel",
        arguments={},
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="جلدية",
        result=result,
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_specialty",
        },
    )

    assert validation.valid is False

    assert (
        validation.reason
        == "contextual_capability_mismatch"
    )


def test_accepts_normal_new_request_without_context():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.cancel",
        arguments={},
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="عايز ألغي الحجز",
        result=result,
        context={},
    )

    assert validation.valid is True


def test_accepts_ambiguous_result():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="ambiguous",
        capability=None,
        arguments={},
        confirmation="unknown",
        ambiguity_kind="needs_clarification",
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="عايز أغيره",
        result=result,
        context={},
    )

    assert validation.valid is True

def test_rejects_copied_old_context_arguments():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={
            "date_text": "الأحد",
            "time_text": "الساعة ستة",
        },
        confirmation="yes",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="لا خليه الاتنين",
        result=result,
        context={
            "active_capability":
                "appointment.reschedule",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation":
                True,

            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
    )

    assert validation.valid is False

    assert validation.reason == (
        "copied_context_argument"
    )


def test_rejects_confirmation_when_replacement_given():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={
            "date_text": "الاتنين",
        },
        confirmation="yes",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="لا خليه الاتنين",
        result=result,
        context={
            "active_capability":
                "appointment.reschedule",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation":
                True,

            "collected_arguments": {
                "date_text": "الأحد",
            },
        },
    )

    assert validation.valid is False

    assert validation.reason == (
        "replacement_with_confirmation"
    )


def test_rejects_correction_target_when_replacement_present():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.create",
        arguments={
            "patient_name": "آية محمد",
        },
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target="patient_name",
        reason="",
    )

    validation = validator.validate(
        message="لا الاسم الصح آية محمد",
        result=result,
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation":
                True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
            },
        },
    )

    assert validation.valid is False

    assert validation.reason == (
        "correction_target_has_replacement"
    )


def test_allows_valid_replacement_correction():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={
            "date_text": "الاتنين",
        },
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="لا خليه الاتنين",
        result=result,
        context={
            "active_capability":
                "appointment.reschedule",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation":
                True,

            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
    )

    assert validation.valid is True    

def test_rejects_yes_confirmation_after_clear_no():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={},
        confirmation="yes",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="لا خليه الاتنين",
        result=result,
        context={
            "active_capability":
                "appointment.reschedule",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation":
                True,

            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
    )

    assert validation.valid is False

    assert validation.reason == (
        "confirmation_contradicts_message"
    )

def test_rejects_no_confirmation_after_clear_yes():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="appointment.create",
        arguments={},
        confirmation="no",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="أيوه تمام",
        result=result,
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation":
                True,
        },
    )

    assert validation.valid is False

    assert validation.reason == (
        "confirmation_contradicts_message"
    )   


def test_allows_slots_query_during_booking_context():

    validator = ToolPlanValidator()

    result = ToolPlan(
        status="selected",
        capability="provider.get_slots",
        arguments={
            "date_text": "الثلاثاء",
        },
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validation = validator.validate(
        message="مواعيد يوم الثلاثاء",
        result=result,
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_time",
        },
    )

    assert validation.valid is True
    assert validation.reason == ""         