from __future__ import annotations

import threading
import time

import pytest

from medmind.understanding.capabilities import (
    CAPABILITY_BY_NAME,
)
from medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)


class BlockingRouter:
    """
    Simulates a synchronous SentenceTransformer encode()
    that gets stuck.

    The Event lets the test release the background thread
    after the request has already escaped through the timeout.
    """

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def route(
        self,
        message,
        *,
        top_k,
        allowed_capabilities=None,
    ):
        self.calls += 1
        self.started.set()

        self.release.wait(
            timeout=2.0
        )

        return []


class FakePlan:

    status = "selected"
    capability = "appointment.create"
    arguments = {}
    confirmation = "unknown"
    correction_target = None
    ambiguity_kind = None
    reason = "fake_planner_success"


class FastPlanner:

    def __init__(self) -> None:
        self.received_candidates = []

    async def plan(
        self,
        *,
        message,
        candidates,
        context,
    ):
        self.received_candidates = list(
            candidates
        )

        return FakePlan()


@pytest.mark.asyncio
async def test_router_stall_does_not_block_understanding():

    router = BlockingRouter()
    planner = FastPlanner()

    orchestrator = UnderstandingOrchestrator(
        router=router,
        planner=planner,
        top_k=8,
        router_timeout_seconds=0.10,
        total_timeout_seconds=1.0,
    )

    started = time.perf_counter()

    try:

        result = await orchestrator.understand(
            message="عايز أحجز",
            context={},
        )

    finally:

        # Let the worker thread finish immediately.
        router.release.set()

    elapsed_seconds = (
        time.perf_counter()
        - started
    )

    # ========================================================
    # REQUEST ESCAPED THE BLOCKING ROUTER
    # ========================================================

    assert elapsed_seconds < 0.50

    # ========================================================
    # FULL REGISTRY WAS USED AS DEGRADATION PATH
    # ========================================================

    assert len(
        planner.received_candidates
    ) == len(
        CAPABILITY_BY_NAME
    )

    # ========================================================
    # PLANNER WAS STILL ABLE TO COMPLETE THE REQUEST
    # ========================================================

    assert result.status == "selected"

    assert (
        result.capability
        == "appointment.create"
    )

    assert result.attempts == 1

@pytest.mark.asyncio
async def test_router_timeout_does_not_start_overlapping_inference():

    router = BlockingRouter()
    planner = FastPlanner()

    orchestrator = UnderstandingOrchestrator(
        router=router,
        planner=planner,
        top_k=8,
        router_timeout_seconds=0.10,
        total_timeout_seconds=1.0,
    )

    try:

        first_result = await orchestrator.understand(
            message="test first request",
            context={},
        )

        assert first_result.status == "selected"

        # The first worker thread is still blocked here,
        # even though the request already escaped via timeout.
        assert router.calls == 1

        second_result = await orchestrator.understand(
            message="test second request",
            context={},
        )

        assert second_result.status == "selected"

        # A second semantic-router inference must NOT start
        # while the first background inference is still alive.
        assert router.calls == 1

    finally:

        router.release.set()
