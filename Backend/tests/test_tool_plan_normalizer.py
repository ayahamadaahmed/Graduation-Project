from agent.medmind.understanding.tool_plan_normalizer import (
    normalize_tool_plan,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)


def _plan(
    *,
    arguments=None,
    correction_target=None,
    confirmation="unknown",
):

    return ToolPlan(
        status="selected",
        capability="appointment.create",
        arguments=arguments or {},
        confirmation=confirmation,
        ambiguity_kind=None,
        correction_target=correction_target,
        reason="",
    )


def test_removes_patient_name_target_when_replacement_exists():

    result = normalize_tool_plan(
        _plan(
            arguments={
                "patient_name": "آية محمد",
            },
            correction_target="patient_name",
        )
    )

    assert result.arguments == {
        "patient_name": "آية محمد",
    }

    assert (
        result.correction_target
        is None
    )


def test_removes_time_target_when_replacement_exists():

    result = normalize_tool_plan(
        _plan(
            arguments={
                "time_text": "الساعة ستة",
            },
            correction_target="time",
        )
    )

    assert result.correction_target is None


def test_removes_doctor_target_when_replacement_exists():

    result = normalize_tool_plan(
        _plan(
            arguments={
                "doctor_name": "دكتورة منى",
            },
            correction_target="doctor",
        )
    )

    assert result.correction_target is None


def test_keeps_target_when_no_replacement_exists():

    result = normalize_tool_plan(
        _plan(
            arguments={},
            correction_target="phone",
        )
    )

    assert (
        result.correction_target
        == "phone"
    )


def test_does_not_modify_unrelated_target():

    result = normalize_tool_plan(
        _plan(
            arguments={
                "patient_name": "آية محمد",
            },
            correction_target="phone",
        )
    )

    assert (
        result.correction_target
        == "phone"
    )


def test_does_not_change_confirmation():

    result = normalize_tool_plan(
        _plan(
            arguments={
                "date_text": "الاتنين",
            },
            correction_target="schedule",
            confirmation="yes",
        )
    )

    assert result.correction_target is None

    # Important:
    # the normalizer must NOT hide a bad confirmation.
    # The validator should reject it afterwards.
    assert result.confirmation == "yes"

def test_normalizer_removes_confirmation_when_replacement_is_present():

    from medmind.understanding.tool_plan_normalizer import (
        normalize_tool_plan,
    )

    from medmind.understanding.tool_planner import (
        ToolPlan,
    )

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={
            "date_text": "الاتنين",
        },
        confirmation="no",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    normalized = normalize_tool_plan(
        result,
        context={
            "active_capability": "appointment.reschedule",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
    )

    assert normalized.arguments == {
        "date_text": "الاتنين",
    }

    assert normalized.confirmation == "unknown"

    assert (
        normalized.capability
        == "appointment.reschedule"
    )    

def test_normalizer_moves_date_expression_out_of_time_text():

    from medmind.understanding.tool_plan_normalizer import (
        normalize_tool_plan,
    )

    from medmind.understanding.tool_planner import (
        ToolPlan,
    )

    result = ToolPlan(
        status="selected",
        capability="appointment.reschedule",
        arguments={
            "time_text": "الاتنين",
        },
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    normalized = normalize_tool_plan(
        result,
        context={
            "active_capability": "appointment.reschedule",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
    )

    assert normalized.arguments == {
        "date_text": "الاتنين",
    }

    assert normalized.confirmation == "unknown"

    assert (
        normalized.capability
        == "appointment.reschedule"
    )    

def test_removes_unchanged_arguments_copied_from_context():

    result = ToolPlan(
        status="selected",
        capability="provider.get_services",
        arguments={
            "doctor_name": "دكتور ماهر",
            "specialty_name": "جلدية",
        },
        confirmation="unknown",
    )

    normalized = normalize_tool_plan(
        result,
        context={
            "collected_arguments": {
                "doctor_name": "دكتور ماهر",
                "specialty_name": "جلدية",
            },
        },
        message="طب الكشف بكام؟",
    )

    assert normalized.arguments == {}


def test_keeps_context_value_when_user_mentions_it_again():

    result = ToolPlan(
        status="selected",
        capability="provider.get_working_hours",
        arguments={
            "doctor_name": "دكتور ماهر",
        },
        confirmation="unknown",
    )

    normalized = normalize_tool_plan(
        result,
        context={
            "collected_arguments": {
                "doctor_name": "دكتور ماهر",
            },
        },
        message="طب دكتور ماهر بيشتغل امتى؟",
    )

    assert normalized.arguments == {
        "doctor_name": "دكتور ماهر",
    }    