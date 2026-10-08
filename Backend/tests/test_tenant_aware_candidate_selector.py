from __future__ import annotations

from medmind.understanding.capability_router import (
    CapabilityMatch,
)
from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)


class FakeRouter:

    def __init__(self):
        self.calls = []

    def route(
        self,
        message: str,
        *,
        top_k: int,
        allowed_capabilities=None,
    ):
        self.calls.append(
            {
                "message": message,
                "top_k": top_k,
                "allowed_capabilities":
                    allowed_capabilities,
            }
        )

        return [
            CapabilityMatch(
                name="provider.get_services",
                domain="provider",
                score=0.9,
                matched_text="services",
            )
        ]


def test_selector_passes_allowed_capabilities_to_router():

    router = FakeRouter()

    allowed = frozenset(
        {
            "provider.get_services",
            "provider.get_slots",
        }
    )

    select_capability_candidates(
        router=router,
        message="عندكم خدمات ايه",
        allowed_capabilities=allowed,
    )

    assert (
        router.calls[0][
            "allowed_capabilities"
        ]
        == allowed
    )


def test_disallowed_active_capability_is_not_injected():

    router = FakeRouter()

    allowed = frozenset(
        {
            "provider.get_services",
        }
    )

    result = select_capability_candidates(
        router=router,
        message="التاني",
        context={
            "active_capability":
                "provider.search_doctors",
        },
        allowed_capabilities=allowed,
    )

    names = {
        item.name
        for item in result
    }

    assert (
        "provider.search_doctors"
        not in names
    )


def test_allowed_active_capability_is_injected():

    router = FakeRouter()

    allowed = frozenset(
        {
            "provider.get_services",
            "appointment.create",
        }
    )

    result = select_capability_candidates(
        router=router,
        message="بكرة",
        context={
            "active_capability":
                "appointment.create",
        },
        allowed_capabilities=allowed,
    )

    names = {
        item.name
        for item in result
    }

    assert (
        "appointment.create"
        in names
    )


def test_legacy_mode_keeps_active_capability_behavior():

    router = FakeRouter()

    result = select_capability_candidates(
        router=router,
        message="بكرة",
        context={
            "active_capability":
                "appointment.create",
        },
        allowed_capabilities=None,
    )

    names = {
        item.name
        for item in result
    }

    assert (
        "appointment.create"
        in names
    )