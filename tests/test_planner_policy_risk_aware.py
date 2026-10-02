from medmind.understanding.capability_router import (
    CapabilityMatch,
)

from medmind.understanding.planner_policy import (
    choose_planner_provider,
)


def _candidate(
    name: str,
    score: float,
) -> CapabilityMatch:
    return CapabilityMatch(
        name=name,
        domain=name.split(".")[0],
        score=score,
        matched_text="",
    )


def test_multiple_conditions_route_to_gpt():

    decision = choose_planner_provider(
        message=(
            "لو مفيش بكرة شوفلي بعده "
            "بس يكون بعد الساعة خمسة"
        ),
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
        candidates=[
            _candidate(
                "appointment.create",
                0.7020,
            ),
            _candidate(
                "appointment.cancel",
                0.4863,
            ),
            _candidate(
                "provider.get_slots",
                0.4372,
            ),
        ],
    )

    assert decision.provider == "gpt"


def test_conditional_competing_operations_route_to_gpt():

    decision = choose_planner_provider(
        message=(
            "شوف حجزي الأول ولو موجود "
            "غيره للاتنين"
        ),
        context={},
        candidates=[
            _candidate(
                "appointment.search",
                0.5952,
            ),
            _candidate(
                "appointment.create",
                0.5895,
            ),
            _candidate(
                "appointment.reschedule",
                0.5670,
            ),
        ],
    )

    assert decision.provider == "gpt"


def test_low_margin_provider_query_stays_qwen():

    decision = choose_planner_provider(
        message="مواعيد العمل إيه؟",
        context={},
        candidates=[
            _candidate(
                "provider.get_working_hours",
                0.6584,
            ),
            _candidate(
                "provider.get_slots",
                0.6169,
            ),
            _candidate(
                "provider.get_policy",
                0.6147,
            ),
        ],
    )

    assert decision.provider == "qwen"


def test_short_contextual_low_margin_stays_qwen():

    decision = choose_planner_provider(
        message="جلدية",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_specialty",
        },
        candidates=[
            _candidate(
                "provider.search_doctors",
                0.6281,
            ),
            _candidate(
                "provider.get_services",
                0.5893,
            ),
            _candidate(
                "appointment.create",
                0.4572,
            ),
        ],
    )

    assert decision.provider == "qwen"