from agent.medmind.understanding.stage_fast_lane import (
    try_stage_fast_lane,
)

from agent.medmind.understanding.confirmation_fast_lane import (
    try_confirmation_fast_lane,
)


def test_safe_deterministic_fast_paths():

    # Phone
    phone = try_stage_fast_lane(
        message="01012345678",
        context={
            "stage": "awaiting_phone",
            "active_capability":
                "appointment.create",
        },
    )

    assert phone is not None
    assert phone.arguments == {
        "phone": "01012345678",
    }

    # National ID
    national_id = try_stage_fast_lane(
        message="29801011234567",
        context={
            "stage":
                "awaiting_national_id",
            "active_capability":
                "appointment.create",
        },
    )

    assert national_id is not None
    assert national_id.arguments == {
        "national_id":
            "29801011234567",
    }

    # Clear yes
    yes = try_confirmation_fast_lane(
        message="ايوه",
        context={
            "stage":
                "awaiting_confirmation",
            "active_capability":
                "appointment.create",
        },
    )

    assert yes is not None
    assert yes.confirmation == "yes"

    # IMPORTANT:
    # complex confirmation must NOT fast-path.
    complex_confirmation = (
        try_confirmation_fast_lane(
            message="ايوه بس غير الميعاد",
            context={
                "stage":
                    "awaiting_confirmation",
                "active_capability":
                    "appointment.create",
            },
        )
    )

    assert complex_confirmation is None

    # Side question must NOT become phone.
    side_question = (
        try_stage_fast_lane(
            message=(
                "الدكتور موجود الجمعة؟"
            ),
            context={
                "stage":
                    "awaiting_phone",
                "active_capability":
                    "appointment.create",
            },
        )
    )

    assert side_question is None