from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.security.tokens import (
    TokenError,
    create_access_token,
    decode_access_token,
)


TEST_SECRET = (
    "test-secret-not-production-"
    "0123456789abcdef0123456789abcdef"
)

SIGNER_SECRET = (
    "signer-secret-not-production-"
    "0123456789abcdef0123456789abcdef"
)

DIFFERENT_SECRET = (
    "different-secret-not-production-"
    "abcdef0123456789abcdef0123456789"
)


def test_access_token_round_trip():

    settings = Settings(
        jwt_secret_key=SecretStr(
            TEST_SECRET
        ),
        jwt_algorithm="HS256",
        jwt_access_token_minutes=15,
    )

    user_id = uuid4()
    membership_id = uuid4()
    provider_id = uuid4()

    token = create_access_token(
        user_id=user_id,
        membership_id=membership_id,
        provider_id=provider_id,
        settings=settings,
    )

    claims = decode_access_token(
        token,
        settings=settings,
    )

    assert (
        claims.user_id
        == user_id
    )

    assert (
        claims.membership_id
        == membership_id
    )

    assert (
        claims.provider_id
        == provider_id
    )


def test_wrong_secret_rejected():

    signer = Settings(
        jwt_secret_key=SecretStr(
            SIGNER_SECRET
        ),
    )

    verifier = Settings(
        jwt_secret_key=SecretStr(
            DIFFERENT_SECRET
        ),
    )

    token = create_access_token(
        user_id=uuid4(),
        membership_id=uuid4(),
        provider_id=uuid4(),
        settings=signer,
    )

    with pytest.raises(
        TokenError
    ):

        decode_access_token(
            token,
            settings=verifier,
        )


def test_missing_secret_rejected():

    settings = Settings(
        jwt_secret_key=None,
    )

    with pytest.raises(
        RuntimeError
    ):

        create_access_token(
            user_id=uuid4(),
            membership_id=uuid4(),
            provider_id=uuid4(),
            settings=settings,
        )