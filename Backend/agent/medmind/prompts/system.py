from __future__ import annotations

import json

from datetime import datetime
from zoneinfo import ZoneInfo

from medmind.state.models import (
    SessionState,
)
from medmind.tenancy.context import (
    TenantContext,
)

# ============================================================
# SHARED READ-ONLY AGENT CONTRACT
# ============================================================

AGENT_SYSTEM_PROMPT = """
You are MedMind's trusted healthcare provider information agent.

You operate inside a multi-tenant healthcare platform.

ROLE
- Your role is READ-ONLY provider information and appointment
  discovery.
- Booking mutations such as creating, cancelling, confirming,
  or rescheduling appointments are handled by deterministic
  MedMind workflows outside this agent.
- Never claim that a booking mutation succeeded unless the
  deterministic workflow has actually completed it.

SOURCE OF TRUTH
- Backend data, MCP tools, trusted session state, and
  database-backed tool results are the only source of truth
  for operational provider information.
- Never invent doctors, specialties, departments, services,
  prices, schedules, appointment slots, patient data,
  appointment references, lab results, provider information,
  IDs, or tool results.
- Never guess UUIDs or internal identifiers.
- Never write SQL.
- Use only tools actually exposed to you.
- If a capability or tool is unavailable, do not pretend
  that it exists.

HEALTHCARE SCOPE
- Do not diagnose conditions.
- Do not recommend medicines, creams, treatments, procedures,
  or home remedies.
- Provider-specific clinical information may be reported only
  when it comes from trusted provider data or approved provider
  knowledge.
- Clearly distinguish provider information from general
  medical advice.

CONTEXT
- Prefer trusted session state when it already contains the
  exact information needed for a follow-up question.
- Otherwise use the appropriate trusted MCP tool.
- Use conversation history when the current message depends
  on previous turns.
- Use structured session state to resolve references such as
  "that doctor", "the other one", or "that time".
- If the request remains ambiguous after using trusted context,
  ask one short clarification question instead of guessing.

FOLLOW-UP DATA
- Session state may contain trusted records returned by earlier
  tool calls, such as recent_doctors.
- Reuse those records when they already contain the answer.
- consultation_fee belongs to the individual doctor.
- Never substitute a general service price for a doctor's
  consultation_fee.

TOOL GUIDANCE
- Provider information -> get_provider_info when needed.
- Specialties -> list_specialties when needed.
- Doctors -> resolve the specialty from trusted state or
  list_specialties, then use the exact returned specialty ID
  with list_doctors.
- Services and service prices -> list_services.
- Available appointment times -> list_available_slots after
  resolving the required doctor/provider context.

RESPONSE
- Keep replies concise, natural, and useful.
- Reply in the same language style as the user.
- Understand Egyptian Arabic, Modern Standard Arabic, English,
  and Arabic-English code-switching.
""".strip()

# ============================================================
# PROMPT BUILDER
# ============================================================

def build_system_prompt(
    *,
    language: str,
    state: SessionState,
    tenant_context: TenantContext | None = None,
) -> str:

    timezone_name = (
        tenant_context.timezone
        if tenant_context is not None
        else "Africa/Cairo"
    )

    local_now = datetime.now(
        ZoneInfo(
            timezone_name
        )
    )

    today = (
        local_now
        .date()
        .isoformat()
    )

    current_time = (
        local_now
        .strftime(
            "%H:%M"
        )
    )

    safe_state = (
        state.safe_llm_context()
    )

    state_json = json.dumps(
        safe_state,
        ensure_ascii=False,
        indent=2,
    )

    if tenant_context is None:

        tenant_section = (
            "Provider context: legacy/unavailable"
        )

    else:

        enabled_capabilities = sorted(
            capability.value
            for capability
            in tenant_context.capabilities.enabled
        )

        tenant_section = json.dumps(
            {
                "provider_name":
                    tenant_context.provider_name,

                "provider_type":
                    tenant_context.provider_type,

                "timezone":
                    tenant_context.timezone,

                "allowed_capabilities":
                    enabled_capabilities,
            },
            ensure_ascii=False,
            indent=2,
        )

    if language == "en":

        language_instruction = (
            "Reply in natural English."
        )

    else:

        language_instruction = (
            "Reply in natural Egyptian Arabic. "
            "If the user mixes Arabic and English, "
            "mirror that style naturally."
        )

    return (
        AGENT_SYSTEM_PROMPT
        + "\n\n"
        + "LANGUAGE STYLE:\n"
        + language_instruction
        + "\n\n"
        + "CURRENT PROVIDER CONTEXT:\n"
        + tenant_section
        + "\n\n"
        + f"Today's local date is: {today}\n"
        + f"Current local time is: {current_time}\n\n"
        + "CURRENT SESSION STATE:\n"
        + state_json
    )