from dataclasses import (
    dataclass,
)
from typing import Literal
from uuid import UUID


CallbackKind = Literal[
    "org",
    "provider",
    "branch",
    "restart",
]


@dataclass(
    frozen=True
)
class ParsedCallback:
    kind: CallbackKind
    value: str


def organization_callback(
    org_type: str,
) -> str:
    if org_type not in {
        "clinic",
        "hospital",
    }:
        raise ValueError(
            "Unsupported organization type."
        )

    return f"org:{org_type}"


def provider_callback(
    provider_id: UUID | str,
) -> str:
    value = str(
        UUID(str(provider_id))
    )

    return f"provider:{value}"


def branch_callback(
    branch_id: UUID | str,
) -> str:
    value = str(
        UUID(str(branch_id))
    )

    return f"branch:{value}"


def restart_callback() -> str:
    return "restart:onboarding"


def parse_callback(
    data: str,
) -> ParsedCallback:
    value = data.strip()

    if ":" not in value:
        raise ValueError(
            "Invalid callback data."
        )

    kind, raw_value = value.split(
        ":",
        maxsplit=1,
    )

    if kind == "org":
        if raw_value not in {
            "clinic",
            "hospital",
        }:
            raise ValueError(
                "Invalid organization type."
            )

        return ParsedCallback(
            kind="org",
            value=raw_value,
        )

    if kind in {
        "provider",
        "branch",
    }:
        normalized_id = str(
            UUID(raw_value)
        )

        return ParsedCallback(
            kind=kind,
            value=normalized_id,
        )

    if (
        kind == "restart"
        and raw_value == "onboarding"
    ):
        return ParsedCallback(
            kind="restart",
            value=raw_value,
        )

    raise ValueError(
        "Unsupported callback data."
    )