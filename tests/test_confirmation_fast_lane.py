from agent.medmind.understanding.confirmation_fast_lane import (
    try_confirmation_fast_lane,
)


def test_fast_lane_accepts_clear_yes():

    result = try_confirmation_fast_lane(
        message="أيوه",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result is not None
    assert result.capability == "appointment.create"
    assert result.confirmation == "yes"


def test_fast_lane_accepts_clear_no():

    result = try_confirmation_fast_lane(
        message="لأ",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.cancel",
        },
    )

    assert result is not None
    assert result.capability == "appointment.cancel"
    assert result.confirmation == "no"


def test_fast_lane_rejects_complex_correction():

    result = try_confirmation_fast_lane(
        message="لا الاسم غلط",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result is None


def test_fast_lane_rejects_operation_switch():

    result = try_confirmation_fast_lane(
        message="لا متلغهوش، غيره للسبت",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.cancel",
        },
    )

    assert result is None


def test_fast_lane_rejects_yes_with_extra_change():

    result = try_confirmation_fast_lane(
        message="أيوه بس الدكتور غلط",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result is None


def test_fast_lane_requires_confirmation_stage():

    result = try_confirmation_fast_lane(
        message="أيوه",
        context={
            "stage": "awaiting_specialty",
            "active_capability": "appointment.create",
        },
    )

    assert result is None


def test_fast_lane_requires_active_capability():

    result = try_confirmation_fast_lane(
        message="أيوه",
        context={
            "stage": "awaiting_confirmation",
        },
    )

    assert result is None


def test_phone_confirmation_fast_lane_accepts_yes():

    result = try_confirmation_fast_lane(
        message="أيوه",
        context={
            "stage": "awaiting_phone_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result is not None
    assert result.capability == "appointment.create"
    assert result.confirmation == "yes"


def test_phone_confirmation_fast_lane_accepts_no():

    result = try_confirmation_fast_lane(
        message="لأ",
        context={
            "stage": "awaiting_phone_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result is not None
    assert result.capability == "appointment.create"
    assert result.confirmation == "no"


def test_phone_confirmation_fast_lane_rejects_complex_message():

    result = try_confirmation_fast_lane(
        message="لا الرقم غلط",
        context={
            "stage": "awaiting_phone_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result is None    