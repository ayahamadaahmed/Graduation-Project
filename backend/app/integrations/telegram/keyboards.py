from collections.abc import (
    Iterable,
)
from typing import Any


def inline_keyboard(
    rows: list[list[dict[str, str]]],
) -> dict[str, Any]:
    return {
        "inline_keyboard": rows,
    }


def organization_keyboard() -> dict:
    return inline_keyboard(
        [
            [
                {
                    "text": "عيادة",
                    "callback_data": (
                        "org:clinic"
                    ),
                },
                {
                    "text": "مستشفى",
                    "callback_data": (
                        "org:hospital"
                    ),
                },
            ]
        ]
    )


def provider_keyboard(
    providers: Iterable[dict],
) -> dict:
    rows: list[list[dict[str, str]]] = []

    for provider in providers:
        rows.append(
            [
                {
                    "text": str(
                        provider["name"]
                    ),
                    "callback_data": (
                        "provider:"
                        f"{provider['id']}"
                    ),
                }
            ]
        )

    rows.append(
        [
            {
                "text": "رجوع",
                "callback_data": (
                    "restart:onboarding"
                ),
            }
        ]
    )

    return inline_keyboard(rows)


def branch_keyboard(
    branches: Iterable[dict],
    *,
    language: str,
) -> dict:
    rows: list[list[dict[str, str]]] = []

    for branch in branches:
        if language == "en":
            name = (
                branch.get("name_en")
                or branch.get("name_ar")
                or branch.get("code")
            )
        else:
            name = (
                branch.get("name_ar")
                or branch.get("name_en")
                or branch.get("code")
            )

        rows.append(
            [
                {
                    "text": str(name),
                    "callback_data": (
                        "branch:"
                        f"{branch['id']}"
                    ),
                }
            ]
        )

    rows.append(
        [
            {
                "text": "ابدأ من جديد",
                "callback_data": (
                    "restart:onboarding"
                ),
            }
        ]
    )

    return inline_keyboard(rows)