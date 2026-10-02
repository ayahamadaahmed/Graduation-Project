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