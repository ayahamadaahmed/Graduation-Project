from __future__ import annotations

import logging
import time
import asyncio

from typing import Any
from pydantic import ValidationError

from .tool_plan_validator import (
    ToolPlanValidationResult,
    ToolPlanValidator,
)
from .capability_router import (
    CapabilityMatch,
)

from .tool_planner import (
    ToolPlan,
)
from .tool_plan_normalizer import (
    normalize_tool_plan,
)
from .planner_policy import (
    choose_planner_provider,
)
# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)


# ============================================================
# FALLBACK TOOL PLANNER
# ============================================================

class FallbackToolPlanner:

    """
    Run the primary planner first.

    Use the fallback planner ONLY when the primary planner
    fails technically, for example:

    - timeout
    - provider/API error
    - invalid JSON
    - invalid ToolPlan
    - invalid capability selection

    A valid ambiguous result is NOT a failure.
    """

    def __init__(
        self,
        *,
        primary,
        fallback,
        circuit_failure_threshold: int = 2,
        circuit_cooldown_seconds: float = 30.0,
        fallback_hedge_delay_seconds: float | None = None,
        primary_timeout_seconds: float | None = None,
    ) -> None:

        if (
            primary_timeout_seconds is not None
            and primary_timeout_seconds <= 0
        ):
            raise ValueError(
                "primary_timeout_seconds "
                "must be greater than zero."
            )

        if (
            fallback_hedge_delay_seconds is not None
            and fallback_hedge_delay_seconds <= 0
        ):
            raise ValueError(
                "fallback_hedge_delay_seconds "
                "must be greater than zero."
            )

        if (
            fallback_hedge_delay_seconds is not None
            and primary_timeout_seconds is not None
            and fallback_hedge_delay_seconds
            >= primary_timeout_seconds
        ):
            raise ValueError(
                "fallback_hedge_delay_seconds "
                "must be lower than "
                "primary_timeout_seconds."
            )

        self.primary = primary
        self.fallback = fallback

        self.validator = ToolPlanValidator()

        self.primary_timeout_seconds = (
            primary_timeout_seconds
        )

        self.fallback_hedge_delay_seconds = (
            fallback_hedge_delay_seconds
        )
        
        self.circuit_failure_threshold = (
            circuit_failure_threshold
        )

        self.circuit_cooldown_seconds = (
            circuit_cooldown_seconds
        )

        self._primary_failure_count = 0
        self._circuit_open_until = 0.0

    # ========================================================
    # CIRCUIT BREAKER
    # ========================================================

    def _is_primary_circuit_open(
        self,
    ) -> bool:

        return (
            time.monotonic()
            < self._circuit_open_until
        )


    def _record_primary_success(
        self,
    ) -> None:

        self._primary_failure_count = 0
        self._circuit_open_until = 0.0


    def _record_primary_failure(
        self,
    ) -> None:

        self._primary_failure_count += 1

        if (
            self._primary_failure_count
            >= self.circuit_failure_threshold
        ):

            self._circuit_open_until = (
                time.monotonic()
                + self.circuit_cooldown_seconds
            )

            logger.warning(
                "planner_primary_circuit_open "
                "failure_count=%s "
                "cooldown_seconds=%.2f",
                self._primary_failure_count,
                self.circuit_cooldown_seconds,
            )   


    def _post_process(
        self,
        *,
        message: str,
        result: ToolPlan,
        context: dict[str, Any] | None,
    ) -> tuple[
        ToolPlan,
        ToolPlanValidationResult,
    ]:

        normalized_result = (
            normalize_tool_plan(
                result,
                context=context,
                message=message,
            )
        )

        validation = (
            self.validator.validate(
                message=message,
                result=normalized_result,
                context=context,
            )
        )

        return (
            normalized_result,
            validation,
        )

    def _finalize_fallback_result(
        self,
        *,
        message: str,
        result: ToolPlan,
        context: dict[str, Any] | None,
    ) -> ToolPlan:

        normalized_result, validation = (
            self._post_process(
                message=message,
                result=result,
                context=context,
            )
        )

        if validation.valid:
            return normalized_result

        logger.warning(
            "planner_fallback_semantic_rejected "
            "reason=%s "
            "capability=%s",
            validation.reason,
            normalized_result.capability,
        )

        return ToolPlan(
            status="ambiguous",
            capability=None,
            arguments={},
            confirmation="unknown",
            ambiguity_kind="needs_clarification",
            reason="semantic_validation_failed",
        )

    @staticmethod
    async def _discard_background_task(
        task: asyncio.Task | None,
        *,
        name: str,
    ) -> None:

        if task is None:
            return

        if not task.done():
            task.cancel()

        try:
            await task

        except asyncio.CancelledError:
            pass

        except Exception as exc:
            logger.info(
                "planner_background_task_discarded "
                "name=%s "
                "error_type=%s",
                name,
                type(exc).__name__,
            )    

    # ========================================================
    # PLAN
    # ========================================================

    async def plan(
        self,
        *,
        message: str,
        candidates: list[
            CapabilityMatch
        ],
        context: dict[
            str,
            Any,
        ]
        | None = None,
    ) -> ToolPlan:

        total_started = (
            time.perf_counter()
        )

        # ========================================================
        # PLANNER POLICY
        #
        # Simple/common turns use Qwen for low latency.
        # Complex turns go directly to GPT-4.1.
        # ========================================================

        policy_decision = (
            choose_planner_provider(
                message=message,
                context=context,
                candidates=candidates,
            )
        )

        logger.info(
            "planner_policy "
            "provider=%s "
            "reason=%s "
            "complexity_score=%s "
            "complexity_level=%s "
            "semantic_margin=%s "
            "signals=%s",
            policy_decision.provider,
            policy_decision.reason,
            policy_decision.complexity_score,
            policy_decision.complexity_level,
            (
                f"{policy_decision.semantic_margin:.4f}"
                if policy_decision.semantic_margin
                is not None
                else "none"
            ),
            policy_decision.signals,
        )

        # ========================================================
        # COMPLEX REQUEST -> GPT DIRECTLY
        #
        # Do not call Qwen first.
        # This avoids paying:
        #
        # Qwen latency + GPT latency
        #
        # for requests that the policy already considers complex.
        # ========================================================

        if (
            policy_decision.provider
            == "gpt"
        ):

            fallback_started = (
                time.perf_counter()
            )

            result = await self.fallback.plan(
                message=message,
                candidates=candidates,
                context=context,
            )

            result = self._finalize_fallback_result(
                message=message,
                result=result,
                context=context,
            )

            fallback_ms = (
                time.perf_counter()
                - fallback_started
            ) * 1000

            total_ms = (
                time.perf_counter()
                - total_started
            ) * 1000

            logger.info(
                "planner_fallback_timing "
                "policy_provider=gpt "
                "policy_reason=%s "
                "primary_success=False "
                "primary_skipped=True "
                "fallback_used=True "
                "primary_ms=0.00 "
                "fallback_ms=%.2f "
                "total_ms=%.2f "
                "status=%s "
                "capability=%s",
                policy_decision.reason,
                fallback_ms,
                total_ms,
                result.status,
                result.capability,
            )

            return result
        
        # ====================================================
        # PRIMARY CIRCUIT OPEN -> GPT DIRECTLY
        # ====================================================

        if self._is_primary_circuit_open():

            fallback_started = (
                time.perf_counter()
            )

            result = await self.fallback.plan(
                message=message,
                candidates=candidates,
                context=context,
            )

            result = self._finalize_fallback_result(
                message=message,
                result=result,
                context=context,
            )

            fallback_ms = (
                time.perf_counter()
                - fallback_started
            ) * 1000

            total_ms = (
                time.perf_counter()
                - total_started
            ) * 1000

            remaining_cooldown = max(
                0.0,
                self._circuit_open_until
                - time.monotonic(),
            )

            logger.warning(
                "planner_primary_circuit_skip "
                "failure_count=%s "
                "remaining_cooldown_seconds=%.2f "
                "fallback_ms=%.2f "
                "total_ms=%.2f "
                "status=%s "
                "capability=%s",
                self._primary_failure_count,
                remaining_cooldown,
                fallback_ms,
                total_ms,
                result.status,
                result.capability,
            )

            return result
        # ====================================================
        # PRIMARY
        # ====================================================

        primary_started = (
            time.perf_counter()
        )

        primary_response_received = False
        primary_task = None
        fallback_task = None

        try:

            primary_call = self.primary.plan(
                message=message,
                candidates=candidates,
                context=context,
            )

            if self.primary_timeout_seconds is None:

                result = await primary_call

            elif self.fallback_hedge_delay_seconds is None:

                result = await asyncio.wait_for(
                    primary_call,
                    timeout=self.primary_timeout_seconds,
                )

            else:

                primary_task = asyncio.create_task(
                    primary_call
                )

                done, _ = await asyncio.wait(
                    {primary_task},
                    timeout=self.fallback_hedge_delay_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if primary_task in done:

                    result = primary_task.result()

                else:

                    fallback_task = asyncio.create_task(
                        self.fallback.plan(
                            message=message,
                            candidates=candidates,
                            context=context,
                        )
                    )

                    logger.info(
                        "planner_fallback_hedge_started "
                        "delay_ms=%.2f",
                        (
                            self.fallback_hedge_delay_seconds
                            * 1000
                        ),
                    )

                    remaining_timeout = (
                        self.primary_timeout_seconds
                        - self.fallback_hedge_delay_seconds
                    )

                    result = await asyncio.wait_for(
                        primary_task,
                        timeout=remaining_timeout,
                    )    

            self._record_primary_success()
            primary_response_received = True

            normalized_result = normalize_tool_plan(
                result,
                context=context,
                message=message,
            )

            if normalized_result is not result:

                logger.info(
                    "planner_primary_normalized "
                    "capability=%s "
                    "old_correction_target=%s "
                    "new_correction_target=%s",
                    result.capability,
                    result.correction_target,
                    normalized_result.correction_target,
                )

            result = normalized_result

            validation = self.validator.validate(
                message=message,
                result=result,
                context=context,
            )


            if not validation.valid:

                primary_ms = (
                    time.perf_counter()
                    - primary_started
                ) * 1000

                logger.warning(
                    "planner_primary_semantic_rejected "
                    "primary_ms=%.2f "
                    "reason=%s "
                    "capability=%s",
                    primary_ms,
                    validation.reason,
                    result.capability,
                )

                fallback_started = (
                    time.perf_counter()
                )

                if fallback_task is not None:

                    fallback_result = await fallback_task
                    fallback_task = None

                else:

                    fallback_result = await self.fallback.plan(
                        message=message,
                        candidates=candidates,
                        context=context,
                    )

                fallback_result = self._finalize_fallback_result(
                    message=message,
                    result=fallback_result,
                    context=context,
                )

                fallback_ms = (
                    time.perf_counter()
                    - fallback_started
                ) * 1000

                total_ms = (
                    time.perf_counter()
                    - total_started
                ) * 1000

                logger.info(
                    "planner_semantic_fallback_timing "
                    "semantic_rejected=True "
                    "validation_reason=%s "
                    "primary_ms=%.2f "
                    "fallback_ms=%.2f "
                    "total_ms=%.2f "
                    "status=%s "
                    "capability=%s",
                    validation.reason,
                    primary_ms,
                    fallback_ms,
                    total_ms,
                    fallback_result.status,
                    fallback_result.capability,
                )

                return fallback_result

            primary_ms = (
                time.perf_counter()
                - primary_started
            ) * 1000

            total_ms = (
                time.perf_counter()
                - total_started
            ) * 1000

            await self._discard_background_task(
                fallback_task,
                name="fallback_hedge",
            )

            fallback_task = None

            logger.info(
                "planner_fallback_timing "
                "primary_success=True "
                "fallback_used=False "
                "primary_ms=%.2f "
                "fallback_ms=0.00 "
                "total_ms=%.2f "
                "status=%s "
                "capability=%s",
                primary_ms,
                total_ms,
                result.status,
                result.capability,
            )

            return result

        except asyncio.CancelledError:

            await self._discard_background_task(
                primary_task,
                name="primary",
            )

            await self._discard_background_task(
                fallback_task,
                name="fallback_hedge",
            )

            raise

        except Exception as exc:

            if primary_response_received:
                raise

            primary_ms = (
                time.perf_counter()
                - primary_started
            ) * 1000

            is_validation_error = isinstance(
                exc,
                ValidationError,
            )

            if not is_validation_error:
                self._record_primary_failure()

            logger.warning(
                "planner_primary_failed "
                "primary_ms=%.2f "
                "error_type=%s "
                "circuit_failure_recorded=%s",
                primary_ms,
                type(exc).__name__,
                not is_validation_error,
            )

        # ====================================================
        # FALLBACK
        # ====================================================

        fallback_started = (
            time.perf_counter()
        )

        if fallback_task is not None:

            result = await fallback_task
            fallback_task = None

        else:

            result = await self.fallback.plan(
                message=message,
                candidates=candidates,
                context=context,
            )

        result = self._finalize_fallback_result(
            message=message,
            result=result,
            context=context,
        )

        fallback_ms = (
            time.perf_counter()
            - fallback_started
        ) * 1000

        total_ms = (
            time.perf_counter()
            - total_started
        ) * 1000

        logger.info(
            "planner_fallback_timing "
            "primary_success=False "
            "fallback_used=True "
            "primary_ms=%.2f "
            "fallback_ms=%.2f "
            "total_ms=%.2f "
            "status=%s "
            "capability=%s",
            primary_ms,
            fallback_ms,
            total_ms,
            result.status,
            result.capability,
        )

        return result