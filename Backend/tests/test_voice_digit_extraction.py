from voice_gateway.main import (
    extract_spoken_digits,
    is_valid_digit_candidate_for_stage,
)


def test_extract_spoken_digits_normal_words() -> None:

    assert (
        extract_spoken_digits(
            "واحد اتنين تلاتة"
        )
        == "123"
    )


def test_extract_spoken_digits_compound_words() -> None:

    assert (
        extract_spoken_digits(
            "خمسةستة"
        )
        == "56"
    )


def test_extract_spoken_digits_multiple_compounds() -> None:

    assert (
        extract_spoken_digits(
            "واحداتنين تلاتة اربعة خمسةستة سبعة تمانية تسعة"
        )
        == "123456789"
    )


def test_extract_spoken_digits_mixed_numbers_and_words() -> None:

    assert (
        extract_spoken_digits(
            "12345 خمسةستة 7 8 9"
        )
        == "1234556789"
    )


def test_extract_national_id_hamsa_style_transcript() -> None:

    transcript = (
        "واحد اتنين تلاتة اربعة "
        "خمسةستة سبعة تمانية تسعة "
        "واحد اتنين تلاتة اربعة خمسة"
    )

    assert (
        extract_spoken_digits(
            transcript
        )
        == "12345678912345"
    )


def test_normal_non_digit_word_is_ignored() -> None:

    assert (
        extract_spoken_digits(
            "مستشفى جلدية"
        )
        == ""
    )


def test_valid_egyptian_mobile_candidates() -> None:

    assert is_valid_digit_candidate_for_stage(
        stage="awaiting_phone",
        digits="01012345678",
    )

    assert is_valid_digit_candidate_for_stage(
        stage="awaiting_phone",
        digits="01112345678",
    )

    assert is_valid_digit_candidate_for_stage(
        stage="awaiting_phone",
        digits="01212345678",
    )

    assert is_valid_digit_candidate_for_stage(
        stage="awaiting_phone",
        digits="01512345678",
    )


def test_invalid_egyptian_mobile_prefix_is_rejected() -> None:

    assert not is_valid_digit_candidate_for_stage(
        stage="awaiting_phone",
        digits="20123456789",
    )

    assert not is_valid_digit_candidate_for_stage(
        stage="awaiting_phone",
        digits="01312345678",
    )


def test_invalid_mobile_length_is_rejected() -> None:

    assert not is_valid_digit_candidate_for_stage(
        stage="awaiting_phone",
        digits="0101234567",
    )


def test_national_id_candidate_requires_14_digits() -> None:

    assert is_valid_digit_candidate_for_stage(
        stage="awaiting_national_id",
        digits="12345678912345",
    )

    assert not is_valid_digit_candidate_for_stage(
        stage="awaiting_national_id",
        digits="1234567891234",
    )    