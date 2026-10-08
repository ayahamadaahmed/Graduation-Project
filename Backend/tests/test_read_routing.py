from __future__ import annotations

from medmind.core.read_routing import (
    resolve_read_route,
)


def test_capability_route_is_preferred():

    route = resolve_read_route(
        selected_capability=(
            "provider.get_slots"
        ),
        intent="ask_doctor",
    )

    assert route == "available_slots"


def test_legacy_intent_is_used_without_capability():

    route = resolve_read_route(
        selected_capability=None,
        intent="ask_service",
    )

    assert route == "service"


def test_unmapped_capability_can_use_legacy_fallback():

    route = resolve_read_route(
        selected_capability=(
            "appointment.search"
        ),
        intent="ask_provider",
    )

    assert route == "knowledge"


def test_knowledge_capabilities_share_knowledge_route():

    assert (
        resolve_read_route(
            selected_capability=(
                "provider.get_policy"
            ),
            intent=None,
        )
        == "knowledge"
    )

    assert (
        resolve_read_route(
            selected_capability=(
                "knowledge.search"
            ),
            intent=None,
        )
        == "knowledge"
    )


def test_unknown_read_returns_none():

    route = resolve_read_route(
        selected_capability=None,
        intent="book_appointment",
    )

    assert route is None