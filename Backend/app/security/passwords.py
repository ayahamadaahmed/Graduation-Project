from functools import lru_cache

import bcrypt


BCRYPT_ROUNDS = 12


def hash_password(
    password: str,
) -> str:

    if not isinstance(
        password,
        str,
    ):
        raise TypeError(
            "password must be a string."
        )

    if not password:
        raise ValueError(
            "password is required."
        )

    password_bytes = (
        password.encode(
            "utf-8"
        )
    )

    # bcrypt has a 72-byte input limit.
    if len(password_bytes) > 72:
        raise ValueError(
            "password is too long."
        )

    salt = bcrypt.gensalt(
        rounds=BCRYPT_ROUNDS,
    )

    hashed = bcrypt.hashpw(
        password_bytes,
        salt,
    )

    return hashed.decode(
        "utf-8"
    )


def verify_password(
    password: str,
    password_hash: str,
) -> bool:

    if not password:
        return False

    if not password_hash:
        return False

    try:

        password_bytes = (
            password.encode(
                "utf-8"
            )
        )

        if len(password_bytes) > 72:
            return False

        return bcrypt.checkpw(
            password_bytes,
            password_hash.encode(
                "utf-8"
            ),
        )

    except (
        ValueError,
        TypeError,
    ):
        return False


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password(
        "medmind-timing-equalizer-not-a-password"
    )


def burn_password_check(
    password: str,
) -> None:
    """Spend the same bcrypt time as a real check when there is no
    account to check against, so response time does not reveal
    whether an email exists."""

    verify_password(
        password,
        _dummy_password_hash(),
    )
