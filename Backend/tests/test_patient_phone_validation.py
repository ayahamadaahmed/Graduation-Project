import pytest
from fastapi import HTTPException

from app.services.patient_service import (
    PatientService,
)


@pytest.mark.parametrize(
    (
        "value",
        "expected",
    ),
    [
        (
            "01012345678",
            "01012345678",
        ),
        (
            "+201012345678",
            "01012345678",
        ),
        (
            "20 10 1234 5678",
            "01012345678",
        ),
        (
            "٠١٠١٢٣٤٥٦٧٨",
            "01012345678",
        ),
        (
            "010-1234-5678",
            "01012345678",
        ),
    ],
)
def test_normalize_valid_egyptian_mobile(
    value,
    expected,
):
    assert (
        PatientService
        ._normalize_phone(
            value
        )
        == expected
    )


@pytest.mark.parametrize(
    "value",
    [
        "0199828292",
        "01912345678",
        "12345678",
        "+14155552671",
        "abc01012345678",
    ],
)
def test_reject_invalid_egyptian_mobile(
    value,
):
    with pytest.raises(
        HTTPException
    ) as exc_info:

        PatientService._normalize_phone(
            value
        )

    assert (
        exc_info.value.status_code
        == 422
    )

    assert (
        exc_info.value.detail[
            "code"
        ]
        == "INVALID_PHONE"
    )