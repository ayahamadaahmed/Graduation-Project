from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from uuid import (
    UUID,
    uuid4,
)

import jwt
from jwt import (
    ExpiredSignatureError,
    InvalidTokenError,
)

from app.core.config import (
    Settings,
    get_settings,
)


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    membership_id: UUID
    provider_id: UUID
    jti: UUID


class TokenError(Exception):
    pass


def _get_jwt_secret(
    settings: Settings,
) -> str:

    if settings.jwt_secret_key is None:
        raise RuntimeError(
            "JWT_SECRET_KEY is required."
        )

    secret = (
        settings.jwt_secret_key
        .get_secret_value()
        .strip()
    )

    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY is required."
        )

    return secret


def create_access_token(
    *,
    user_id: UUID,
    membership_id: UUID,
    provider_id: UUID,
    settings: Settings | None = None,
) -> str:

    settings = (
        settings
        or get_settings()
    )

    if settings.jwt_access_token_minutes <= 0:
        raise RuntimeError(
            "JWT_ACCESS_TOKEN_MINUTES "
            "must be greater than zero."
        )

    secret = _get_jwt_secret(
        settings
    )

    now = datetime.now(
        timezone.utc
    )

    expires_at = (
        now
        + timedelta(
            minutes=(
                settings
                .jwt_access_token_minutes
            )
        )
    )

    payload = {
        "sub": str(user_id),
        "membership_id":
            str(membership_id),
        "provider_id":
            str(provider_id),
        "token_type": "access",
        "jti": str(uuid4()),
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        secret,
        algorithm=(
            settings.jwt_algorithm
        ),
    )


def decode_access_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> AccessTokenClaims:

    settings = (
        settings
        or get_settings()
    )

    secret = _get_jwt_secret(
        settings
    )

    try:

        payload = jwt.decode(
            token,
            secret,
            algorithms=[
                settings.jwt_algorithm
            ],
            options={
                "require": [
                    "sub",
                    "membership_id",
                    "provider_id",
                    "token_type",
                    "jti",
                    "iat",
                    "exp",
                ],
            },
        )

        if (
            payload.get("token_type")
            != "access"
        ):
            raise TokenError(
                "Invalid token type."
            )

        return AccessTokenClaims(
            user_id=UUID(
                payload["sub"]
            ),
            membership_id=UUID(
                payload[
                    "membership_id"
                ]
            ),
            provider_id=UUID(
                payload[
                    "provider_id"
                ]
            ),
            jti=UUID(
                payload["jti"]
            ),
        )

    except ExpiredSignatureError as exc:

        raise TokenError(
            "Access token expired."
        ) from exc

    except (
        InvalidTokenError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:

        raise TokenError(
            "Invalid access token."
        ) from exc