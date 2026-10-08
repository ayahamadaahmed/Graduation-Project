from __future__ import annotations

import json
import logging
import time
from .context_compressor import (
    compress_understanding_context,
)
from typing import (
    Any,
    Literal,
)

from langchain_openai import (
    ChatOpenAI,
)

from pydantic import (
    BaseModel,
    Field,
)

from .capabilities import (
    get_capability,
)

from .capability_router import (
    CapabilityMatch,
)


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)


# ============================================================
# OUTPUT
# ============================================================

class ToolPlan(BaseModel):

    status: Literal[
        "selected",
        "ambiguous",
    ]

    capability: str | None = None

    arguments: dict[str, str] = Field(
        default_factory=dict
    )

    confirmation: Literal[
        "yes",
        "no",
        "unknown",
    ] = "unknown"

    ambiguity_kind: Literal[
        "needs_clarification",
        "candidate_miss",
    ] | None = None

    correction_target: Literal[
        "patient_name",
        "phone",
        "doctor",
        "schedule",
        "time",
        "national_id",
    ] | None = None

    reason: str = ""


# ============================================================
# COMPACT PLANNER INSTRUCTIONS
# ============================================================
# ============================================================
# SHARED PLANNER BEHAVIOR
# ============================================================

PLANNER_BEHAVIOR_INSTRUCTIONS = """
You are MedMind's capability planner.

Your only job is to understand the CURRENT user message,
use the supplied conversation context, and select the best
capability from CANDIDATE CAPABILITIES.

LANGUAGE
- Understand Egyptian Arabic, Modern Standard Arabic,
  English, and Arabic-English code-switching.
- Preserve user-provided names, dates, times, and identifiers
  in their original wording when possible.

SCOPE
- MedMind handles appointment operations and information
  about the CURRENT healthcare provider.
- Never diagnose a condition.
- Never recommend medicines, creams, treatments, procedures,
  or home remedies.
- Never invent provider data, doctors, specialties, services,
  prices, schedules, IDs, or database values.
- knowledge.search is provider-bounded.
- Do not use knowledge.search for general diagnosis,
  medication, or treatment advice.

DIAGNOSTICS
- MedMind may analyze attached pathology/laboratory reports
  and supported radiology images for decision support.
- diagnostics.pathology.analyze is for attached lab/pathology reports.
- diagnostics.radiology.analyze requires an explicit modality.
- Supported radiology modalities are exactly:
  chest_xray, brain_mri, kidney_ct.
- Never guess radiology modality.
- Never choose a modality based on confidence, filename, or image content.
- If radiology analysis is requested but modality is not explicitly known,
  return ambiguous with needs_clarification.
- Diagnostic output is decision support and must not be presented as a
  confirmed clinical diagnosis.

ROUTING
- Select ONLY from CANDIDATE CAPABILITIES.
- Choose the user's CURRENT operation, not merely the topic.
- active_capability is context, not a restriction.
- Explicit operation switches are allowed.
- Informational side questions may select a read-only
  capability during an active appointment workflow.
- Missing workflow fields do not make a clear operation
  ambiguous.

APPOINTMENTS
- New booking -> appointment.create.
- Existing appointment lookup -> appointment.search.
- Cancel existing appointment -> appointment.cancel.
- Change an existing appointment -> appointment.reschedule.
- Correcting an in-progress appointment keeps the active
  appointment capability.

ARGUMENTS
- Return only values newly stated, selected, corrected, or
  changed in the CURRENT message.
- Never copy unchanged values from conversation context.
- Preserve spoken date/time wording.
- Never invent argument values.

SERVICES AND MEDICAL SCOPE
- A symptom, condition, or health goal is NOT automatically
  a specialty or service_name.
- If the user asks for "something for" a condition and
  provider.get_services is available, route to the provider's
  actual services instead of giving medical advice.
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
- Do not select appointment.create unless the user clearly
  asks to book or is continuing an active booking flow.

SERVICE RESOLUTION
- Only when stage=awaiting_service AND offered_services exists,
  resolve the user's wording against offered_services.
- Match Egyptian Arabic, English, paraphrases, colloquial
  wording, goals, and synonyms.
- If exactly one offered service clearly matches, return its
  EXACT value as service_name.
- Never invent a service outside offered_services.
- If multiple services are plausible, omit service_name so
  the workflow can clarify.

Examples:

stage=new
User: "عايزة حاجة للتصبغات"
-> provider.get_services
-> no invented service_name

stage=new
User: "استخدم كريم ايه للتصبغات؟"
-> provider.get_services when available
-> no medical recommendation

stage=awaiting_service
offered_services=[
    "Dermatology Consultation",
    "Melasma and Pigmentation Treatment"
]
User: "خدمة التصبغات"
-> service_name="Melasma and Pigmentation Treatment"

User: "مين دكاترة الجلدية عندكم؟"
-> provider.search_doctors

User: "دكتور ماهر متخصص في ايه؟"
-> knowledge.search

User: "عايزة أحجز جلدية"
-> appointment.create

CONFIRMATION
- yes/no is confirmation only when a confirmation is pending.
- Replacement data is a correction, not confirmation.
- When replacement data is supplied:
  confirmation="unknown".

CORRECTIONS
- If replacement data is supplied, return it in arguments.
- If a field is wrong but no replacement value is supplied,
  set correction_target.
- Normally leave correction_target null when replacement data
  is already present.

AMBIGUITY
- needs_clarification:
  the requested operation cannot safely be determined from
  the current message and context.
- candidate_miss:
  the operation is clear but is absent from candidates.
- Do not mark a clear operation ambiguous merely because
  optional workflow fields are missing.

OUTPUT
- status="selected":
  capability is required and ambiguity_kind must be null.
- status="ambiguous":
  capability must be null.
- Keep reason short.
""".strip()

# Temporary compatibility alias.
# Qwen will be migrated to the shared contract in the next step.
PLANNER_INSTRUCTIONS = (
    PLANNER_BEHAVIOR_INSTRUCTIONS
)

def _normalize_modality_text(
    value: str,
) -> str:

    normalized = value.strip().lower()

    aliases = {
        "chest xray": "chest_xray",
        "chest x-ray": "chest_xray",
        "chest_xray": "chest_xray",

        "brain mri": "brain_mri",
        "brain_mri": "brain_mri",

        "kidney ct": "kidney_ct",
        "renal ct": "kidney_ct",
        "kidney_ct": "kidney_ct",
    }

    return aliases.get(
        normalized,
        normalized,
    )

# ============================================================
# TOOL PLANNER
# ============================================================

class ToolPlanner:

    def __init__(
        self,
        *,
        model: ChatOpenAI,
    ) -> None:

        self.model = model

        self.structured_model = (
            model.with_structured_output(
                ToolPlan,
                method="function_calling",
            )
        )

    # ========================================================
    # BUILD CANDIDATE CONTEXT
    # ========================================================

    @staticmethod
    def _build_candidate_text(
        candidates: list[CapabilityMatch],
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
                ", ".join(argument_names)
                if argument_names
                else "none"
            )

            lines.append(
                (
                    f"{capability.name} | "
                    f"{capability.description_ar} | "
                    f"args={arguments_text}"
                )
            )

        return "\n".join(lines)

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
                ambiguity_kind=(
                    "candidate_miss"
                ),
                reason=(
                    "No candidate capabilities."
                ),
            )

        candidate_names = {
            candidate.name
            for candidate in candidates
        }

        # ----------------------------------------------------
        # BUILD PROMPT
        # ----------------------------------------------------

        build_started = (
            time.perf_counter()
        )

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

        prompt = f"""
{PLANNER_INSTRUCTIONS}


CURRENT CONTEXT

{context_text}


CANDIDATE CAPABILITIES

{candidate_text}


CURRENT USER MESSAGE

{message}
""".strip()

        build_ms = (
            time.perf_counter()
            - build_started
        ) * 1000

        # ----------------------------------------------------
        # LLM INVOCATION
        # ----------------------------------------------------

        invoke_started = (
            time.perf_counter()
        )

        result = await (
            self.structured_model
            .ainvoke(
                prompt
            )
        )

        invoke_ms = (
            time.perf_counter()
            - invoke_started
        ) * 1000

        # ----------------------------------------------------
        # POST-PROCESSING
        # ----------------------------------------------------

        postprocess_started = (
            time.perf_counter()
        )

        if not isinstance(
            result,
            ToolPlan,
        ):

            raise RuntimeError(
                "Tool planner did not "
                "return ToolPlan."
            )

        # ----------------------------------------------------
        # CAPABILITY GUARD
        # ----------------------------------------------------

        if (
            result.status == "selected"
            and result.capability
            not in candidate_names
        ):

            return ToolPlan(
                status="ambiguous",
                capability=None,
                arguments={},
                ambiguity_kind=(
                    "candidate_miss"
                ),
                reason=(
                    "Planner selected a capability "
                    "outside the candidate set."
                ),
            )

        # ----------------------------------------------------
        # ARGUMENT SCHEMA GUARD
        # ----------------------------------------------------

        if (
            result.status
            == "selected"
            and result.capability
            is not None
        ):

            capability = get_capability(
                result.capability
            )

            if capability is None:

                return ToolPlan(
                    status="ambiguous",
                    capability=None,
                    arguments={},
                    ambiguity_kind=(
                        "candidate_miss"
                    ),
                    reason=(
                        "Unknown selected capability."
                    ),
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

        # ----------------------------------------------------
        # TIMING
        # ----------------------------------------------------

        postprocess_ms = (
            time.perf_counter()
            - postprocess_started
        ) * 1000

        total_ms = (
            time.perf_counter()
            - plan_started
        ) * 1000

        # ----------------------------------------------------
        # SAFE PROFILING LOG
        #
        # Never log:
        # - message
        # - prompt
        # - context values
        # - argument values
        # - national ID
        # - phone
        # - patient name
        # ----------------------------------------------------

        logger.info(
            "tool_planner_timing "
            "candidate_count=%s "
            "candidate_chars=%s "
            "context_chars=%s "
            "prompt_chars=%s "
            "build_ms=%.2f "
            "invoke_ms=%.2f "
            "postprocess_ms=%.2f "
            "total_ms=%.2f "
            "status=%s "
            "capability=%s "
            "argument_keys=%s",
            len(candidates),
            len(candidate_text),
            len(context_text),
            len(prompt),
            build_ms,
            invoke_ms,
            postprocess_ms,
            total_ms,
            result.status,
            result.capability,
            sorted(
                result.arguments.keys()
            ),
        )

        return result