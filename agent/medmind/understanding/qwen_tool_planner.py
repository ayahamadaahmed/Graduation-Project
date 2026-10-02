from __future__ import annotations

import asyncio
import json
import logging
import time
import httpx
from typing import Any

from groq import AsyncGroq

from .capabilities import (
    get_capability,
)
from .context_compressor import (
    compress_understanding_context,
)
from .capability_router import (
    CapabilityMatch,
)
from .tool_planner import (
    ToolPlan,
)

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)
# ============================================================
# QWEN OUTPUT CONTRACT
# ============================================================

QWEN_OUTPUT_INSTRUCTIONS = """
Return exactly one JSON object with this shape:

{
  "status": "selected" | "ambiguous",
  "capability": string | null,
  "arguments": {},
  "confirmation": "yes" | "no" | "unknown",
  "ambiguity_kind": "needs_clarification" | "candidate_miss" | null,
  "correction_target": "patient_name" | "phone" | "doctor" |
                       "schedule" | "time" | "national_id" | null,
  "reason": ""
}

For status="selected":
- capability is required.
- ambiguity_kind must be null.
- reason must be "".

For status="ambiguous":
- capability must be null.
- reason must be short.
""".strip()

QWEN_BEHAVIOR_INSTRUCTIONS = """
Select the best capability for the CURRENT user message
using the supplied context and CANDIDATE CAPABILITIES.

Understand Egyptian Arabic, Modern Standard Arabic, English,
and Arabic-English code-switching. Preserve user-stated names,
dates, times, and identifiers.

Rules:
- Select ONLY from CANDIDATE CAPABILITIES.
- active_capability is context, not a restriction.
- Explicit operation switches and read-only side questions
  are allowed.
- New booking -> appointment.create.
- Existing appointment lookup -> appointment.search.
- Cancel -> appointment.cancel.
- Change/reschedule -> appointment.reschedule.
- Missing workflow fields do not make a clear operation
  ambiguous.
- Return only arguments newly stated, selected, corrected,
  or changed in the CURRENT message.
- Never copy unchanged values from context.
- Never invent argument values or provider data.
- Preserve spoken date/time wording.
- Never diagnose or recommend medicines or treatments.
- knowledge.search is provider-bounded.
- A symptom or health goal is not automatically a specialty
  or service_name.
- If provider.get_services is available for a service request,
  prefer the provider's actual services over medical advice.
- Do not invent service_name from a symptom or condition.
- Price/cost/fee questions are provider.get_services.
- If the user asks the price/cost/fee of something explicitly named,
  extract that user-stated phrase as service_name.
- This is extraction, not database resolution.
- Do not invent service_name when the user only asks for general service prices.

Examples:
User: "تساقط الشعر بكام؟"
-> capability=provider.get_services
-> service_name="تساقط الشعر"

User: "سعر علاج تساقط الشعر كام؟"
-> capability=provider.get_services
-> service_name="علاج تساقط الشعر"

User: "سعر الليزر كام؟"
-> capability=provider.get_services
-> service_name="الليزر"

User: "أسعار الخدمات؟"
-> capability=provider.get_services
-> no service_name

User: "أسعار خدمات الجلدية؟"
-> capability=provider.get_services
-> specialty_name="جلدية"
- Only when stage=awaiting_service and offered_services exists,
  resolve wording to exactly one offered service.
- If multiple offered services are plausible, omit service_name.
- yes/no is confirmation only when confirmation is pending.
- Replacement data is a correction; confirmation="unknown".
- If a field is wrong but no replacement is supplied, set
  correction_target.
- Use needs_clarification only when the operation cannot safely
  be determined.
- Use candidate_miss only when the operation is clear but absent
  from candidates.
""".strip()

# ============================================================
# QWEN TOOL PLANNER
# ============================================================

class QwenToolPlanner:

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen/qwen3.6-27b",
        timeout: float = 3.0,
        max_tokens: int = 160,
        http_client: httpx.AsyncClient | None = None,
        service_tier: str = "on_demand",
    ) -> None:

        if not api_key:
            raise ValueError(
                "Groq API key is required."
            )

        if timeout <= 0:
            raise ValueError(
                "timeout must be greater than zero."
            )

        if max_tokens <= 0:
            raise ValueError(
                "max_tokens must be greater than zero."
            )

        self.client = AsyncGroq(
            api_key=api_key,
            max_retries=0,
            http_client=http_client,
        )

        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        if service_tier not in {"on_demand", "flex"}:
            raise ValueError(
                "service_tier must be 'on_demand' or 'flex'."
            )

        self.service_tier = service_tier
        self._warmup_lock = asyncio.Lock()

        self._last_warmup_at: float | None = None

        self._warmup_cooldown_seconds = 45.0

    async def warmup(self) -> bool:
        """
        Warm the Groq HTTP connection without running
       an LLM completion.

        Repeated warm-up calls inside the cooldown window
        are skipped to avoid unnecessary network requests.

        Concurrent callers share the same warm-up lock so
        multiple incoming calls do not trigger duplicate
        Groq requests.
        """

        now = time.perf_counter()

        if (
            self._last_warmup_at is not None
            and (
                now - self._last_warmup_at
                < self._warmup_cooldown_seconds
            )
        ):
            age_seconds = (
                now - self._last_warmup_at
            )

            logger.info(
                "qwen_planner_warmup "
                "model=%s "
                "status=skipped "
                "reason=recent "
                "age_seconds=%.2f",
                self.model,
                age_seconds,
            )

            return True

        async with self._warmup_lock:

            # Another concurrent caller may have completed
            # the warm-up while this caller waited for the lock.
            now = time.perf_counter()

            if (
                self._last_warmup_at is not None
                and (
                    now - self._last_warmup_at
                    < self._warmup_cooldown_seconds
                )
            ):
                age_seconds = (
                    now - self._last_warmup_at
                )

                logger.info(
                    "qwen_planner_warmup "
                    "model=%s "
                    "status=skipped "
                    "reason=recent_after_lock "
                    "age_seconds=%.2f",
                    self.model,
                    age_seconds,
                )

                return True

            started = time.perf_counter()

            try:

                await asyncio.wait_for(
                    self.client.models.list(),
                    timeout=self.timeout,
                )

                elapsed_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                self._last_warmup_at = (
                    time.perf_counter()
                )

                logger.info(
                    "qwen_planner_warmup "
                    "model=%s "
                    "elapsed_ms=%.2f "
                    "status=success",
                    self.model,
                    elapsed_ms,
                )

                return True

            except Exception as exc:

                elapsed_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                logger.warning(
                    "qwen_planner_warmup "
                    "model=%s "
                    "elapsed_ms=%.2f "
                    "status=failed "
                    "error_type=%s",
                    self.model,
                    elapsed_ms,
                    type(exc).__name__,
                )

                return False
    
    # ========================================================
    # BUILD CANDIDATE CONTEXT
    # ========================================================

    @staticmethod
    def _build_candidate_text(
        candidates: list[
            CapabilityMatch
        ],
    ) -> str:

        lines: list[str] = []

        for candidate in candidates:

            capability = get_capability(
                candidate.name
            )

            if capability is None:
                continue

            argument_names = list(
                capability.arguments.keys()
            )

            arguments_text = (
                ",".join(argument_names)
                if argument_names
                else "none"
            )

            matched_text = (
                candidate.matched_text
                or ""
            )

            lines.append(
                (
                    f"{capability.name}"
                    f" | semantic_score="
                    f"{candidate.score:.4f}"
                    f" | matched={matched_text}"
                    f" | {capability.description_ar}"
                    f" | args={arguments_text}"
                )
            )

        return "\n".join(
            lines
        )

    # ========================================================
    # BUILD PROMPT
    # ========================================================

    def _build_prompt(
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
        | None,
    ) -> str:

        candidate_text = (
            self._build_candidate_text(
                candidates
            )
        )

        compressed_context = (
            compress_understanding_context(
                context
            )
        )

        context_text = json.dumps(
            compressed_context,
            ensure_ascii=False,
            default=str,
        )

        return f"""
{QWEN_BEHAVIOR_INSTRUCTIONS}

{QWEN_OUTPUT_INSTRUCTIONS}

CURRENT CONTEXT

{context_text}

CANDIDATE CAPABILITIES

{candidate_text}

CURRENT USER MESSAGE

{message}
""".strip()

    # ========================================================
    # VALIDATE RESULT
    # ========================================================

    @staticmethod
    def _validate_result(
        *,
        result: ToolPlan,
        candidates: list[
            CapabilityMatch
        ],
    ) -> ToolPlan:

        candidate_names = {
            candidate.name
            for candidate in candidates
        }

        # ----------------------------------------------------
        # SELECTED CAPABILITY MUST COME FROM CANDIDATES
        #
        # Unlike the normal GPT planner, this raises.
        # The fallback layer will catch it and call GPT-4.1.
        # ----------------------------------------------------

        if (
            result.status == "selected"
            and result.capability
            not in candidate_names
        ):

            raise RuntimeError(
                "Qwen selected capability outside "
                "the candidate set."
            )

        # ----------------------------------------------------
        # SELECTED RESULT MUST HAVE CAPABILITY
        # ----------------------------------------------------

        if (
            result.status == "selected"
            and not result.capability
        ):

            raise RuntimeError(
                "Qwen returned selected result "
                "without capability."
            )

        # ----------------------------------------------------
        # ARGUMENT SCHEMA GUARD
        # ----------------------------------------------------

        if (
            result.status == "selected"
            and result.capability
            is not None
        ):

            capability = get_capability(
                result.capability
            )

            if capability is None:

                raise RuntimeError(
                    "Qwen selected unknown capability."
                )

            allowed_arguments = set(
                capability.arguments.keys()
            )

            clean_arguments = {
                key: value
                for key, value
                in result.arguments.items()
                if (
                    key in allowed_arguments
                    and isinstance(
                        value,
                        str,
                    )
                    and value.strip()
                )
            }

            result = result.model_copy(
                update={
                    "arguments":
                        clean_arguments,
                }
            )

        return result

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

        plan_started = (
            time.perf_counter()
        )

        # ----------------------------------------------------
        # NO CANDIDATES
        # ----------------------------------------------------

        if not candidates:

            return ToolPlan(
                status="ambiguous",
                capability=None,
                arguments={},
                ambiguity_kind="candidate_miss",
                reason=(
                    "No candidate capabilities."
                ),
            )

        # ----------------------------------------------------
        # BUILD PROMPT
        # ----------------------------------------------------

        prompt = self._build_prompt(
            message=message,
            candidates=candidates,
            context=context,
        )

        # ----------------------------------------------------
        # QWEN INVOCATION
        # ----------------------------------------------------

        invoke_started = (
            time.perf_counter()
        )

        response = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,

                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Return ONLY one valid JSON object. "
                            "Do not use markdown. "
                            "Do not add explanations. "
                            "Do not add text before or after "
                            "the JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],

                # Same configuration that performed well
                # in the controlled Qwen benchmark.
                reasoning_effort="none",
                service_tier=self.service_tier,

                temperature=0,

                response_format={
                    "type": "json_object"
                },

                max_completion_tokens=(
                    self.max_tokens
                ),
            ),

            timeout=self.timeout,
        )

        invoke_ms = (
            time.perf_counter()
            - invoke_started
        ) * 1000

        # ----------------------------------------------------
        # EXTRACT CONTENT
        # ----------------------------------------------------

        raw = (
            response
            .choices[0]
            .message
            .content
        )

        if not raw:
            raise RuntimeError(
                "Qwen returned empty response."
            )

        # ----------------------------------------------------
        # STRICT JSON PARSE
        # ----------------------------------------------------

        try:

            data = json.loads(
                raw
            )

        except json.JSONDecodeError as exc:

            raise RuntimeError(
                "Qwen returned invalid JSON."
            ) from exc

        if not isinstance(
            data,
            dict,
        ):

            raise RuntimeError(
                "Qwen response must be "
                "a JSON object."
            )

        # ----------------------------------------------------
        # PYDANTIC TOOLPLAN VALIDATION
        # ----------------------------------------------------

        result = ToolPlan.model_validate(
            data
        )

        # ----------------------------------------------------
        # CAPABILITY / ARGUMENT GUARDS
        # ----------------------------------------------------

        result = self._validate_result(
            result=result,
            candidates=candidates,
        )

        # ----------------------------------------------------
        # SAFE TIMING
        # ----------------------------------------------------

        total_ms = (
            time.perf_counter()
            - plan_started
        ) * 1000

        usage = getattr(
            response,
            "usage",
            None,
        )


        prompt_tokens = (
            getattr(
                usage,
                "prompt_tokens",
                None,
            )
            if usage
            else None
        )

        completion_tokens = (
            getattr(
                usage,
                "completion_tokens",
                None,
            )
            if usage
            else None
        )

        total_tokens = (
            getattr(
                usage,
                "total_tokens",
                None,
            )
            if usage
            else None
        )

        server_total = (
            getattr(
                usage,
                "total_time",
                None,
            )
            if usage
            else None
        )

        queue_time = (
            getattr(
                usage,
                "queue_time",
                None,
            )
            if usage
            else None
        )

        prompt_time = (
            getattr(
                usage,
                "prompt_time",
                None,
            )
            if usage
            else None
        )

        completion_time = (
            getattr(
                usage,
                "completion_time",
                None,
            )
            if usage
            else None
        )

        server_total_ms = (
            server_total * 1000
            if server_total is not None
            else None
        )

        queue_time_ms = (
            queue_time * 1000
            if queue_time is not None
            else None
        )

        prompt_time_ms = (
            prompt_time * 1000
            if prompt_time is not None
            else None
        )

        completion_time_ms = (
            completion_time * 1000
            if completion_time is not None
            else None
        )

        logger.info(
            "qwen_tool_planner_timing "
            "model=%s "
            "candidate_count=%s "
            "prompt_tokens=%s "
            "completion_tokens=%s "
            "total_tokens=%s "
            "invoke_ms=%.2f "
            "server_total_ms=%s "
            "server_queue_ms=%s "
            "server_prompt_ms=%s "
            "server_completion_ms=%s "
            "total_ms=%.2f "
            "status=%s "
            "capability=%s "
            "argument_keys=%s",
            self.model,
            len(candidates),
            (
                prompt_tokens
                if prompt_tokens is not None
                else "unknown"
            ),
            (
                completion_tokens
                if completion_tokens is not None
                else "unknown"
            ),
            (
                total_tokens
                if total_tokens is not None
                else "unknown"
            ),
            invoke_ms,
            (
                f"{server_total_ms:.2f}"
                if server_total_ms is not None
                else "unknown"
            ),

            (
                f"{queue_time_ms:.2f}"
                if queue_time_ms is not None
                else "unknown"
            ),
            (
                f"{prompt_time_ms:.2f}"
                if prompt_time_ms is not None
                else "unknown"
            ),
            (
                f"{completion_time_ms:.2f}"
                if completion_time_ms is not None
                else "unknown"
            ),
            total_ms,
            result.status,
            result.capability,
            sorted(
                result.arguments.keys()
            ),
        )

        return result