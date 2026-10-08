from __future__ import annotations

import logging
import time
import asyncio
import threading
from dataclasses import dataclass
from typing import (
    Any,
    Literal,
)
from medmind.understanding.reference_guard import (
    needs_reference_clarification,
)
from medmind.understanding.capabilities import (
    CAPABILITY_BY_NAME,
)
from medmind.understanding.confirmation_fast_lane import (
    try_confirmation_fast_lane,
)
from medmind.understanding.stage_fast_lane import (
    try_stage_fast_lane,
)
from medmind.understanding.diagnostic_fast_lane import (
    try_diagnostic_fast_lane,
)
from medmind.understanding.capability_router import (
    CapabilityMatch,
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.tool_planner import (
    ToolPlan,
    ToolPlanner,
)


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)


# ============================================================
# TYPES
# ============================================================

class _SemanticRouterBusy(RuntimeError):
    pass


UnderstandingStatus = Literal[
    "selected",
    "ambiguous",
    "fallback_required",
]


AmbiguityKind = Literal[
    "needs_clarification",
    "candidate_miss",
]


# ============================================================
# RESULT
# ============================================================

@dataclass(frozen=True)
class UnderstandingResult:

    status: UnderstandingStatus

    capability: str | None

    arguments: dict[str, str]

    confirmation: Literal[
        "yes",
        "no",
        "unknown",
    ] = "unknown"

    correction_target: Literal[
        "patient_name",
        "phone",
        "doctor",
        "schedule",
        "time",
        "national_id",
    ] | None = None

    ambiguity_kind: AmbiguityKind | None = None

    reason: str = ""

    attempts: int = 1

    used_broad_candidates: bool = False


# ============================================================
# ORCHESTRATOR
# ============================================================

class UnderstandingOrchestrator:

    def __init__(
    self,
    *,
    router: SemanticCapabilityRouter,
    planner: ToolPlanner,
    top_k: int = 8,
    total_timeout_seconds: float = 5.0,
    router_timeout_seconds: float = 0.75,
    allowed_capabilities: (
        set[str]
        | frozenset[str]
        | None
    ) = None,
) -> None:

        if top_k <= 0:
            raise ValueError(
                "top_k must be greater than zero"
            )

        if total_timeout_seconds <= 0:
            raise ValueError(
                "total_timeout_seconds must be greater than zero"
            )

        if router_timeout_seconds <= 0:
            raise ValueError(
                "router_timeout_seconds must be greater than zero"
            )

        if allowed_capabilities is None:

            self.allowed_capabilities = None

        else:

            unknown_capabilities = (
                set(allowed_capabilities)
                - set(CAPABILITY_BY_NAME)
            )

            if unknown_capabilities:
                raise ValueError(
                    "Unknown allowed understanding capabilities: "
                    + ", ".join(
                        sorted(
                            unknown_capabilities
                        )
                    )
                )

            self.allowed_capabilities = frozenset(
                allowed_capabilities
            )    

        self.router = router
        self.planner = planner
        self.top_k = top_k
        self.total_timeout_seconds = (
            total_timeout_seconds
        )
        self.router_timeout_seconds = (
            router_timeout_seconds
        )

        # Only one CPU-heavy semantic-router inference may
        # execute at a time.
        #
        # asyncio.wait_for() can stop waiting for a to_thread()
        # call, but it cannot force-stop the worker thread.
        # This lock prevents a later request from starting a
        # second overlapping model inference while the timed-out
        # worker is still finishing.
        self._router_inference_lock = (
            threading.Lock()
        )

    # ========================================================
    # UNDERSTAND
    # ========================================================

    async def understand(
        self,
        *,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> UnderstandingResult:

        understanding_started = (
            time.perf_counter()
        )

        deadline = (
            time.perf_counter()
            + self.total_timeout_seconds
        )
        router_timed_out = False

        # ----------------------------------------------------
        # Timing values.
        #
        # All start at zero so every path can safely log the
        # same fields without changing orchestration behavior.
        # ----------------------------------------------------

        primary_select_ms = 0.0
        primary_planner_ms = 0.0

        broad_build_ms = 0.0
        broad_planner_ms = 0.0

        primary_candidate_count = 0
        broad_candidate_count = 0

        context = context or {}

        clean_message = message.strip()

        def finish(
            result: UnderstandingResult,
        ) -> UnderstandingResult:

            total_ms = (
                time.perf_counter()
                - understanding_started
            ) * 1000

            logger.info(
                "understanding_timing "
                "primary_candidate_count=%s "
                "primary_select_ms=%.2f "
                "primary_planner_ms=%.2f "
                "broad_candidate_count=%s "
                "broad_build_ms=%.2f "
                "broad_planner_ms=%.2f "
                "router_timed_out=%s "
                "total_ms=%.2f "
                "status=%s "
                "reason=%s "
                "capability=%s "
                "attempts=%s "
                "used_broad=%s "
                "ambiguity_kind=%s",
                primary_candidate_count,
                primary_select_ms,
                primary_planner_ms,
                broad_candidate_count,
                broad_build_ms,
                broad_planner_ms,
                router_timed_out,
                total_ms,
                result.status,
                result.reason,
                result.capability,
                result.attempts,
                result.used_broad_candidates,
                result.ambiguity_kind,
            )

            return result


        async def run_planner_with_budget(
            *,
            candidates: list[CapabilityMatch],
            attempt: int,
        ) -> ToolPlan:

            remaining_seconds = (
                deadline
                - time.perf_counter()
            )

            if remaining_seconds <= 0:
                raise asyncio.TimeoutError

            logger.info(
                "understanding_budget "
                "attempt=%s "
                "remaining_budget_ms=%.2f "
                "candidate_count=%s",
                attempt,
                remaining_seconds * 1000,
                len(candidates),
            )

            return await asyncio.wait_for(
                self.planner.plan(
                    message=clean_message,
                    candidates=candidates,
                    context=context,
                ),
                timeout=remaining_seconds,
            )

        async def run_selector_with_budget(
        ) -> list[CapabilityMatch]:

            remaining_seconds = (
                deadline
                - time.perf_counter()
            )

            if remaining_seconds <= 0:
                raise asyncio.TimeoutError

            selector_timeout = min(
                self.router_timeout_seconds,
                remaining_seconds,
            )

            logger.info(
                "semantic_router_budget "
                "timeout_ms=%.2f "
                "remaining_budget_ms=%.2f",
                selector_timeout * 1000,
                remaining_seconds * 1000,
            )

            def select_single_flight(
            ) -> list[CapabilityMatch]:

                acquired = (
                    self._router_inference_lock.acquire(
                        blocking=False
                    )
                )

                if not acquired:
                    raise _SemanticRouterBusy

                try:
                    return select_capability_candidates(
                        router=self.router,
                        message=clean_message,
                        context=context,
                        top_k=self.top_k,
                        allowed_capabilities=(
                            self.allowed_capabilities
                        ),
                    )

                finally:
                    self._router_inference_lock.release()

            return await asyncio.wait_for(
                asyncio.to_thread(
                    select_single_flight
                ),
                timeout=selector_timeout,
            )

        if not clean_message:

            return finish(
                UnderstandingResult(
                    status="ambiguous",
                    capability=None,
                    arguments={},
                    ambiguity_kind=(
                        "needs_clarification"
                    ),
                    reason="empty_message",
                    attempts=0,
                    used_broad_candidates=False,
                )
            )

        fast_lane_result = (
            try_confirmation_fast_lane(
                message=clean_message,
                context=context,
            )
        )

        if fast_lane_result is not None:

            logger.info(
                "understanding_fast_lane "
                "type=confirmation "
                "capability=%s "
                "confirmation=%s",
                fast_lane_result.capability,
                fast_lane_result.confirmation,
            )

            return finish(
                self._selected_result(
                    result=fast_lane_result,
                    attempts=0,
                    used_broad_candidates=False,
                )
            )

        stage_fast_lane_result = (
            try_stage_fast_lane(
                message=clean_message,
                context=context,
            )
        )

        if stage_fast_lane_result is not None:

            logger.info(
                "understanding_fast_lane "
                "type=stage "
                "stage=%s "
                "capability=%s "
                "argument_keys=%s",
                context.get("stage"),
                stage_fast_lane_result.capability,
                sorted(
                    stage_fast_lane_result
                    .arguments
                    .keys()
                ),
            )

            return finish(
                self._selected_result(
                    result=
                        stage_fast_lane_result,
                    attempts=0,
                    used_broad_candidates=False,
                )
            )

        diagnostic_fast_lane_result = (
            try_diagnostic_fast_lane(
                message=clean_message,
                allowed_capabilities=(
                    self.allowed_capabilities
                ),
            )
        )

        if diagnostic_fast_lane_result is not None:

            logger.info(
                "understanding_fast_lane "
                "type=diagnostic "
                "capability=%s "
                "argument_keys=%s",
                diagnostic_fast_lane_result.capability,
                sorted(
                    diagnostic_fast_lane_result
                    .arguments
                    .keys()
                ),
            )

            return finish(
                self._selected_result(
                    result=(
                        diagnostic_fast_lane_result
                    ),
                    attempts=0,
                    used_broad_candidates=False,
                )
            )

        primary_select_started = (
            time.perf_counter()
        )

        try:

            primary_candidates = (
                await run_selector_with_budget()
            )

        except (
            asyncio.TimeoutError,
            _SemanticRouterBusy,
        ) as exc:

            router_timed_out = isinstance(
                exc,
                asyncio.TimeoutError,
            )

            primary_select_ms = (
                time.perf_counter()
                - primary_select_started
            ) * 1000

            if router_timed_out:

                logger.warning(
                    "semantic_router_timeout "
                    "timeout_ms=%.2f "
                    "fallback=full_registry",
                    self.router_timeout_seconds * 1000,
                )

            else:

                logger.warning(
                    "semantic_router_busy "
                    "fallback=full_registry"
                )

            broad_build_started = (
                time.perf_counter()
            )

            primary_candidates = (
                self._build_broad_candidates(
                    existing_candidates=[],
                )
            )

            broad_build_ms = (
                time.perf_counter()
                - broad_build_started
            ) * 1000

            broad_candidate_count = len(
                primary_candidates
            )

        else:
            primary_select_ms = (
                time.perf_counter()
                - primary_select_started
            ) * 1000

        primary_candidate_count = len(
            primary_candidates
        )
        # ----------------------------------------------------
        # Planner attempt 1.
        # ----------------------------------------------------

        primary_planner_started = (
            time.perf_counter()
        )

        try:

            primary_result = (
                await run_planner_with_budget(
                    candidates=primary_candidates,
                    attempt=1,
                )
            )

        except asyncio.TimeoutError:

            return finish(
                UnderstandingResult(
                    status="fallback_required",
                    capability=None,
                    arguments={},
                    ambiguity_kind=None,
                    reason="understanding_timeout",
                    attempts=1,
                    used_broad_candidates=False,
                )
            )

        primary_planner_ms = (
            time.perf_counter()
            - primary_planner_started
        ) * 1000

        # ====================================================
        # SELECTED
        #
        # Normal successful path.
        # ====================================================

        if (
            primary_result.status
            == "selected"
        ):

            reference_clarification = (
                self._reference_clarification_result(
                    message=clean_message,
                    result=primary_result,
                    context=context,
                    attempts=1,
                    used_broad_candidates=False,
                )
            )

            if reference_clarification is not None:
                return finish(
                    reference_clarification
                )

            return finish(
                self._selected_result(
                    result=primary_result,
                    attempts=1,
                    used_broad_candidates=False,
                )
            )

        # ====================================================
        # NEEDS CLARIFICATION
        #
        # The problem is missing user/context information.
        #
        # Retrying with more capabilities cannot fix that,
        # so STOP immediately.
        # ====================================================

        if (
            primary_result.ambiguity_kind
            == "needs_clarification"
        ):

            return finish(
                UnderstandingResult(
                    status="ambiguous",
                    capability=None,
                    arguments={},
                    ambiguity_kind=(
                        "needs_clarification"
                    ),
                    reason=(
                        primary_result.reason
                        or "needs_clarification"
                    ),
                    attempts=1,
                    used_broad_candidates=False,
                )
            )

        # ====================================================
        # UNKNOWN AMBIGUITY TYPE
        #
        # If the planner said ambiguous but failed to classify
        # why, do not guess and do not waste another model call.
        #
        # Send it to the higher-level fallback layer.
        # ====================================================

        if (
            primary_result.ambiguity_kind
            != "candidate_miss"
        ):

            return finish(
                UnderstandingResult(
                    status="fallback_required",
                    capability=None,
                    arguments={},
                    ambiguity_kind=None,
                    reason=(
                        primary_result.reason
                        or "unclassified_ambiguity"
                    ),
                    attempts=1,
                    used_broad_candidates=False,
                )
            )

        # ====================================================
        # CANDIDATE MISS
        #
        # The user's request appears understandable,
        # but the correct capability may not have been
        # included in the semantic Top-K.
        #
        # Broaden the candidate set and retry once.
        # ====================================================

        broad_build_started = (
            time.perf_counter()
        )

        broad_candidates = (
            self._build_broad_candidates(
                existing_candidates=(
                    primary_candidates
                ),
            )
        )

        broad_build_ms = (
            time.perf_counter()
            - broad_build_started
        ) * 1000

        broad_candidate_count = len(
            broad_candidates
        )

        # ====================================================
        # NO NEW CANDIDATES
        #
        # If Top-K already included the full registry,
        # a second identical call adds no value.
        # ====================================================

        if self._same_candidate_set(
            primary_candidates,
            broad_candidates,
        ):

            return finish(
                UnderstandingResult(
                    status="fallback_required",
                    capability=None,
                    arguments={},
                    ambiguity_kind=(
                        "candidate_miss"
                    ),
                    reason=(
                        primary_result.reason
                        or
                        "candidate_miss_after_full_registry"
                    ),
                    attempts=1,
                    used_broad_candidates=False,
                )
            )

        # ====================================================
        # ATTEMPT 2
        #
        # Retry using the complete capability registry.
        # ====================================================

        broad_planner_started = (
            time.perf_counter()
        )

        try:

            broad_result = (
                await run_planner_with_budget(
                    candidates=broad_candidates,
                    attempt=2,
                )
            )

        except asyncio.TimeoutError:

            return finish(
                UnderstandingResult(
                    status="fallback_required",
                    capability=None,
                    arguments={},
                    ambiguity_kind=None,
                    reason="understanding_timeout",
                    attempts=2,
                    used_broad_candidates=True,
                )
            )

        broad_planner_ms = (
            time.perf_counter()
            - broad_planner_started
        ) * 1000

        # ====================================================
        # RETRY SUCCEEDED
        # ====================================================

        if (
            broad_result.status
            == "selected"
        ):

            reference_clarification = (
                self._reference_clarification_result(
                    message=clean_message,
                    result=broad_result,
                    context=context,
                    attempts=2,
                    used_broad_candidates=True,
                )
            )

            if reference_clarification is not None:
                return finish(
                    reference_clarification
                )

            return finish(
                self._selected_result(
                    result=broad_result,
                    attempts=2,
                    used_broad_candidates=True,
                )
            )
        # ====================================================
        # BROAD RETRY NOW SAYS CLARIFICATION
        #
        # More candidates showed that this is not really a
        # retrieval miss. The user/context is insufficient.
        # ====================================================

        if (
            broad_result.ambiguity_kind
            == "needs_clarification"
        ):

            return finish(
                UnderstandingResult(
                    status="ambiguous",
                    capability=None,
                    arguments={},
                    ambiguity_kind=(
                        "needs_clarification"
                    ),
                    reason=(
                        broad_result.reason
                        or "needs_clarification"
                    ),
                    attempts=2,
                    used_broad_candidates=True,
                )
            )

        # ====================================================
        # STILL UNRESOLVED
        # ====================================================

        return finish(
            UnderstandingResult(
                status="fallback_required",
                capability=None,
                arguments={},
                ambiguity_kind=(
                    broad_result.ambiguity_kind
                ),
                reason=(
                    broad_result.reason
                    or primary_result.reason
                    or "planner_remained_unresolved"
                ),
                attempts=2,
                used_broad_candidates=True,
            )
        )

    # ========================================================
    # BROAD CANDIDATES
    # ========================================================

    def _build_broad_candidates(
        self,
        *,
        existing_candidates: list[
            CapabilityMatch
        ],
    ) -> list[CapabilityMatch]:

        candidates_by_name = {
            candidate.name: candidate
            for candidate
            in existing_candidates
        }

        for capability in (
            CAPABILITY_BY_NAME.values()
        ):
            if (
                self.allowed_capabilities
                is not None
                and capability.name
                not in self.allowed_capabilities
            ):
                continue

            if (
                capability.name
                in candidates_by_name
            ):
                continue

            candidates_by_name[
                capability.name
            ] = CapabilityMatch(
                name=capability.name,
                domain=capability.domain,
                score=0.0,
                matched_text=(
                    "broad_candidate_retry"
                ),
            )

        return list(
            candidates_by_name.values()
        )  

    # ========================================================
    # SAME CANDIDATE SET
    # ========================================================

    @staticmethod
    def _same_candidate_set(
        first: list[CapabilityMatch],
        second: list[CapabilityMatch],
    ) -> bool:

        first_names = {
            candidate.name
            for candidate
            in first
        }

        second_names = {
            candidate.name
            for candidate
            in second
        }

        return (
            first_names
            == second_names
        )

    @staticmethod
    def _reference_clarification_result(
        *,
        message: str,
        result: ToolPlan,
        context: dict,
        attempts: int,
        used_broad_candidates: bool,
    ) -> UnderstandingResult | None:

        if not needs_reference_clarification(
            message=message,
            result=result,
            context=context,
        ):
            return None

        return UnderstandingResult(
            status="ambiguous",
            capability=None,
            arguments={},
            confirmation="unknown",
            ambiguity_kind="needs_clarification",
            reason="unresolved_reference",
            attempts=attempts,
            used_broad_candidates=(
                used_broad_candidates
            ),
        )

    # ========================================================
    # SELECTED RESULT
    # ========================================================

    @staticmethod
    def _selected_result(
        *,
        result: ToolPlan,
        attempts: int,
        used_broad_candidates: bool,
    ) -> UnderstandingResult:

        # Defensive validation:
        #
        # status="selected" without a capability should never
        # be treated as a valid executable result.

        if not result.capability:

            return UnderstandingResult(
                status="fallback_required",
                capability=None,
                arguments={},
                ambiguity_kind=None,
                reason=(
                    "planner_selected_without_capability"
                ),
                attempts=attempts,
                used_broad_candidates=(
                    used_broad_candidates
                ),
            )

        return UnderstandingResult(
            status="selected",
            capability=result.capability,
            arguments=dict(
                result.arguments
            ),
            confirmation=result.confirmation,
            ambiguity_kind=None,
            reason=result.reason,
            attempts=attempts,
            used_broad_candidates=(
                used_broad_candidates
            ),
            correction_target=(
                result.correction_target
            ),
        )