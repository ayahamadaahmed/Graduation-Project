import pytest
from agent.medmind.understanding.planner_policy import (
    choose_planner_provider,
)


# ============================================================
# SIMPLE / FAST PATH -> QWEN
# ============================================================


def test_simple_booking_goes_to_qwen():

    result = choose_planner_provider(
        message="عايزة احجز",
        context={},
    )

    assert result.provider == "qwen"


def test_simple_booking_with_date_goes_to_qwen():

    result = choose_planner_provider(
        message="ممكن أعمل حجز لبكرة؟",
        context={},
    )

    assert result.provider == "qwen"


def test_short_contextual_specialty_goes_to_qwen():

    result = choose_planner_provider(
        message="جلدية",
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_specialty",
        },
    )

    assert result.provider == "qwen"

    assert (
        result.reason
        == "short_contextual_turn"
    )


def test_short_contextual_doctor_goes_to_qwen():

    result = choose_planner_provider(
        message="دكتورة منى",
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_doctor",
        },
    )

    assert result.provider == "qwen"


def test_short_contextual_date_goes_to_qwen():

    result = choose_planner_provider(
        message="بكرة",
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_date",
        },
    )

    assert result.provider == "qwen"


def test_short_confirmation_goes_to_qwen():

    result = choose_planner_provider(
        message="أيوه",
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_confirmation",
        },
    )

    assert result.provider == "qwen"


# ============================================================
# COMPLEX / SMART PATH -> GPT-4.1
# ============================================================


def test_operation_switch_goes_to_gpt():

    result = choose_planner_provider(
        message=(
            "لا متلغهوش، "
            "غيره للسبت"
        ),
        context={
            "active_capability":
                "appointment.cancel",

            "stage":
                "awaiting_confirmation",
        },
    )

    assert result.provider == "gpt"

    assert (
        result.reason
        == "operation_switch"
    )


def test_long_multi_condition_request_goes_to_gpt():

    result = choose_planner_provider(
        message=(
            "أنا عندي حجز الخميس "
            "بس مش هقدر أجي "
            "وشوفلي دكتورة تانية "
            "في نفس التخصص "
            "بعد الساعة ستة"
        ),
        context={},
    )

    assert result.provider == "gpt"

    assert (
        result.reason
        == "long_multi_condition_request"
    )


def test_complex_doctor_request_goes_to_gpt():

    result = choose_planner_provider(
        message=(
            "عايزة دكتورة تانية "
            "في نفس التخصص "
            "ويكون عندها ميعاد "
            "متاح بعد الساعة ستة"
        ),
        context={},
    )

    assert result.provider == "gpt"


# ============================================================
# DEFAULT FAST PATH
# ============================================================


def test_normal_provider_question_stays_qwen():

    result = choose_planner_provider(
        message="كشف الجلدية بكام؟",
        context={},
    )

    assert result.provider == "qwen"

    assert (
        result.reason
        == "default_fast_path"
    )


def test_simple_contextual_turn_has_low_complexity_score():

    result = choose_planner_provider(
        message="جلدية",
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_specialty",
        },
    )

    assert result.provider == "qwen"

    assert (
        result.complexity_level
        == "simple"
    )

    assert (
        result.complexity_score
        <= 0
    )

    assert (
        "short_contextual_turn"
        in result.signals
    )


def test_operation_switch_has_high_complexity_score():

    result = choose_planner_provider(
        message="لا متلغهوش، غيره للسبت",
        context={
            "active_capability":
                "appointment.cancel",

            "stage":
                "awaiting_confirmation",
        },
    )

    assert result.provider == "gpt"

    assert (
        result.complexity_level
        == "complex"
    )

    assert (
        result.complexity_score
        >= 3
    )

    assert (
        "operation_switch"
        in result.signals
    )


def test_multiple_conditions_raise_complexity():

    result = choose_planner_provider(
        message=(
            "عايزة دكتورة جلدية "
            "لو مفيش السبت "
            "شوفلي الأحد "
            "بعد الساعة ستة"
        ),
        context={},
    )

    assert (
        "multiple_conditions"
        in result.signals
    )

    assert (
        result.complexity_score
        >= 2
    )

def test_simple_context_conflict_stays_on_qwen():

    result = choose_planner_provider(
        message="عايزة ألغي الحجز",
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_doctor",
        },
    )

    assert (
        "context_conflict"
        in result.signals
    )

    assert result.provider == "qwen"

    assert (
        result.complexity_level
        == "borderline"
    )

    assert (
        result.complexity_score
        == 1
    )

def test_borderline_request_stays_on_qwen():

    result = choose_planner_provider(
        message="عايزة دكتور تاني",
        context={},
    )

    assert (
        result.complexity_level
        in (
            "simple",
            "borderline",
        )
    )

    assert (
        result.provider
        == "qwen"
    )   

def test_semantic_margin_is_measured():

    class Candidate:

        def __init__(
            self,
            score: float,
        ):
            self.score = score

    result = choose_planner_provider(
        message="عايزة احجز",
        context={},
        candidates=[
            Candidate(0.90),
            Candidate(0.65),
            Candidate(0.40),
        ],
    )

    assert (
        result.semantic_margin
        == pytest.approx(0.25)
    )

    # Measurement must NOT affect routing yet.
    assert result.provider == "qwen"     