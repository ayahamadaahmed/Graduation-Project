from voice_gateway.safety.confirmation_guard import (
    classify_confirmation_action,
    critical_stt_actions_disagree,
    get_critical_stt_retry_prompt,
)


def test_confirmation_classifier_understands_arabic_actions():
    assert (
        classify_confirmation_action(
            "أكد الحجز"
        )
        == "confirm"
    )

    assert (
        classify_confirmation_action(
            "أيوه أكد"
        )
        == "confirm"
    )

    assert (
        classify_confirmation_action(
            "ألغي الحجز"
        )
        == "reject"
    )

    assert (
        classify_confirmation_action(
            "لا"
        )
        == "reject"
    )


def test_conflicting_stt_actions_are_blocked():

    assert critical_stt_actions_disagree(
        hamsa_transcript=
            "أكد الحجز",

        deepgram_transcript=
            "ألغي الحجز",
    ) is True


def test_same_stt_action_is_not_blocked():

    assert critical_stt_actions_disagree(
        hamsa_transcript=
            "أيوه أكد",

        deepgram_transcript=
            "أكد الحجز",
    ) is False


def test_retry_prompt_is_stage_specific():

    assert (
        "رقم الموبايل"
        in get_critical_stt_retry_prompt(
            "awaiting_phone_confirmation"
        )
    )

    assert (
        "ألغي الحجز"
        in get_critical_stt_retry_prompt(
            "awaiting_cancel_confirmation"
        )
    )

def test_cancel_confirmation_is_stage_aware():

    assert (
        classify_confirmation_action(
            "ألغي الحجز",
            stage=(
                "awaiting_cancel_confirmation"
            ),
        )
        == "confirm"
    )

    assert (
        critical_stt_actions_disagree(
            hamsa_transcript="أيوه",
            deepgram_transcript=(
                "ألغي الحجز"
            ),
            stage=(
                "awaiting_cancel_confirmation"
            ),
        )
        is False
    )


def test_cancel_request_rejects_booking_confirmation():

    assert (
        classify_confirmation_action(
            "ألغي الحجز",
            stage="awaiting_confirmation",
        )
        == "reject"
    )


def test_reschedule_confirmation_is_stage_aware():

    assert (
        critical_stt_actions_disagree(
            hamsa_transcript="أيوه",
            deepgram_transcript=(
                "غيّر الميعاد"
            ),
            stage=(
                "awaiting_reschedule_confirmation"
            ),
        )
        is False
    )


def test_phone_confirmation_understands_correct_and_wrong():

    assert (
        classify_confirmation_action(
            "صح",
            stage=(
                "awaiting_phone_confirmation"
            ),
        )
        == "confirm"
    )

    assert (
        classify_confirmation_action(
            "غلط",
            stage=(
                "awaiting_phone_confirmation"
            ),
        )
        == "reject"
    )    