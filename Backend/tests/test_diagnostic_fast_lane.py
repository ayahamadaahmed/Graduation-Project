from medmind.understanding.diagnostic_fast_lane import (
    try_diagnostic_fast_lane,
)


def test_brain_mri_explicit_request():
    result = try_diagnostic_fast_lane(
        message="Analyze this brain MRI",
    )

    assert result is not None
    assert result.status == "selected"
    assert (
        result.capability
        == "diagnostics.radiology.analyze"
    )
    assert result.arguments == {
        "modality": "brain_mri",
    }


def test_chest_xray_explicit_request():
    result = try_diagnostic_fast_lane(
        message="Interpret this chest X-ray",
    )

    assert result is not None
    assert result.arguments == {
        "modality": "chest_xray",
    }


def test_kidney_ct_explicit_request():
    result = try_diagnostic_fast_lane(
        message="حلل الأشعة المقطعية على الكلى",
    )

    assert result is not None
    assert result.arguments == {
        "modality": "kidney_ct",
    }


def test_generic_scan_does_not_guess():
    result = try_diagnostic_fast_lane(
        message="Analyze this scan",
    )

    assert result is None


def test_general_question_does_not_route():
    result = try_diagnostic_fast_lane(
        message="What is a brain MRI?",
    )

    assert result is None


def test_multiple_modalities_do_not_guess():
    result = try_diagnostic_fast_lane(
        message=(
            "Analyze this brain MRI "
            "and kidney CT"
        ),
    )

    assert result is None


def test_negative_request_does_not_route():
    result = try_diagnostic_fast_lane(
        message="Don't analyze this brain MRI",
    )

    assert result is None


def test_tenant_policy_is_respected():
    result = try_diagnostic_fast_lane(
        message="Analyze this brain MRI",
        allowed_capabilities={
            "appointment.create",
        },
    )

    assert result is None