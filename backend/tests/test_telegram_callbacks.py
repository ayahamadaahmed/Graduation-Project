from uuid import uuid4

import pytest

from app.integrations.telegram.callbacks import (
    branch_callback,
    organization_callback,
    parse_callback,
    provider_callback,
)


def test_organization_callback():
    data = organization_callback(
        "clinic"
    )

    parsed = parse_callback(data)

    assert parsed.kind == "org"
    assert parsed.value == "clinic"


def test_provider_callback():
    provider_id = uuid4()

    data = provider_callback(
        provider_id
    )

    parsed = parse_callback(data)

    assert parsed.kind == "provider"
    assert parsed.value == str(provider_id)


def test_branch_callback():
    branch_id = uuid4()

    data = branch_callback(
        branch_id
    )

    parsed = parse_callback(data)

    assert parsed.kind == "branch"
    assert parsed.value == str(branch_id)


def test_invalid_callback_is_rejected():
    with pytest.raises(
        ValueError
    ):
        parse_callback(
            "provider:not-a-uuid"
        )