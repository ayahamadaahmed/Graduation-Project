from voice_gateway.main import (
    DEFAULT_TURN_END_GRACE_SECONDS,
    DIGIT_COLLECTION_STAGES,
    DIGIT_TURN_END_GRACE_SECONDS,
    get_turn_end_grace_seconds,
)


def test_normal_turn_grace_is_200ms() -> None:
    assert DEFAULT_TURN_END_GRACE_SECONDS == 0.20

    assert (
        get_turn_end_grace_seconds(
            "awaiting_confirmation"
        )
        == 0.20
    )


def test_digit_turn_grace_remains_300ms() -> None:
    assert DIGIT_TURN_END_GRACE_SECONDS == 0.30

    digit_stage = next(
        iter(DIGIT_COLLECTION_STAGES)
    )

    assert (
        get_turn_end_grace_seconds(
            digit_stage
        )
        == 0.30
    )


def test_unknown_stage_uses_normal_grace() -> None:
    assert (
        get_turn_end_grace_seconds(
            "new"
        )
        == 0.20
    )

    assert (
        get_turn_end_grace_seconds(
            None
        )
        == 0.20
    )