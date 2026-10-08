import pytest

from app.security.passwords import (
    hash_password,
    verify_password,
)


def test_hash_password_is_not_plaintext():

    password = (
        "StrongPassword123!"
    )

    password_hash = (
        hash_password(
            password
        )
    )

    assert (
        password_hash
        != password
    )

    assert password_hash.startswith(
        "$2b$"
    )


def test_verify_correct_password():

    password = (
        "StrongPassword123!"
    )

    password_hash = (
        hash_password(
            password
        )
    )

    assert verify_password(
        password,
        password_hash,
    )


def test_verify_wrong_password():

    password_hash = (
        hash_password(
            "StrongPassword123!"
        )
    )

    assert not verify_password(
        "WrongPassword123!",
        password_hash,
    )


def test_same_password_gets_different_hashes():

    password = (
        "StrongPassword123!"
    )

    first = hash_password(
        password
    )

    second = hash_password(
        password
    )

    assert first != second


def test_empty_password_rejected():

    with pytest.raises(
        ValueError
    ):

        hash_password(
            ""
        )


def test_password_over_bcrypt_limit_rejected():

    with pytest.raises(
        ValueError
    ):

        hash_password(
            "a" * 73
        )