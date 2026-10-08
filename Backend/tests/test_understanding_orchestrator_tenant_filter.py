from __future__ import annotations

import pytest

from medmind.understanding.capabilities import (
    CAPABILITY_BY_NAME,
)
from medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)
from medmind.understanding.capability_router import (
    CapabilityMatch,
)


class FakeRouter:
    pass


class FakePlanner:
    pass


def make_orchestrator(
    allowed_capabilities=None,
):
    return UnderstandingOrchestrator(
        router=FakeRouter(),
        planner=FakePlanner(),
        allowed_capabilities=(
            allowed_capabilities
        ),
    )


def test_broad_candidates_are_filtered():

    allowed = frozenset(
        {
            "appointment.create",
            "provider.get_services",
            "provider.get_slots",
        }
    )

    orchestrator = make_orchestrator(
        allowed_capabilities=allowed,
    )

    result = (
        orchestrator
        ._build_broad_candidates(
            existing_candidates=[],
        )
    )

    names = {
        item.name
        for item in result
    }

    assert names == set(
        allowed
    )

    assert (
        "provider.search_doctors"
        not in names
    )


def test_legacy_broad_candidates_use_full_registry():

    orchestrator = make_orchestrator(
        allowed_capabilities=None,
    )

    result = (
        orchestrator
        ._build_broad_candidates(
            existing_candidates=[],
        )
    )

    names = {
        item.name
        for item in result
    }

    assert names == set(
        CAPABILITY_BY_NAME
    )


def test_existing_allowed_candidate_is_preserved():

    from medmind.understanding.capability_router import (
        CapabilityMatch,
    )

    allowed = frozenset(
        {
            "provider.get_services",
            "provider.get_slots",
        }
    )

    orchestrator = make_orchestrator(
        allowed_capabilities=allowed,
    )

    existing = [
        CapabilityMatch(
            name="provider.get_services",
            domain="provider",
            score=0.91,
            matched_text="services",
        )
    ]

    result = (
        orchestrator
        ._build_broad_candidates(
            existing_candidates=existing,
        )
    )

    by_name = {
        item.name: item
        for item in result
    }

    assert (
        by_name[
            "provider.get_services"
        ].score
        == 0.91
    )

    assert (
        "provider.get_slots"
        in by_name
    )

