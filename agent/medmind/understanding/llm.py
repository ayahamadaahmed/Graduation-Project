from __future__ import annotations

import json

from langchain_openai import (
    ChatOpenAI,
)

from medmind.memory.models import (
    ChatMessage,
)

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.types import (
    NLUResult,
)

# ============================================================
# LEGACY NLU FALLBACK CONTRACT
# ============================================================

NLU_INSTRUCTIONS = """
You are MedMind's legacy NLU fallback.

Your ONLY job is to understand the CURRENT user message and
return the structured NLU result required by the output schema.

You do not answer the user.
You do not call tools.
You do not execute appointments.
You do not invent database IDs or operational data.

LANGUAGE
- Understand Egyptian Arabic, Modern Standard Arabic,
  English, and Arabic-English code-switching.
- Preserve user-provided names, dates, times, references,
  phone numbers, and identifiers in their original wording
  when possible.

INTENT VS OPERATION TYPE
- intent describes the CURRENT user message.
- operation_type is set only when the user starts a new
  appointment operation or explicitly switches operations.
- Contextual replies inside an existing workflow normally
  have operation_type=null.

APPOINTMENT OPERATIONS
- New booking:
  intent=book_appointment
  operation_type=book_appointment

- Cancel an existing appointment:
  intent=cancel_appointment
  operation_type=cancel_appointment

- Reschedule an existing appointment:
  intent=reschedule_appointment
  operation_type=reschedule_appointment

- Ask about one specific existing appointment:
  intent=lookup_appointment

- Ask to view existing appointments:
  intent=search_appointments

CONTEXTUAL VALUES
Use the current workflow state and recent conversation when
the current message depends on context.

Examples:

stage=awaiting_doctor
User: "منى"
-> intent=provide_doctor
-> doctor_name="منى"
-> operation_type=null

stage=awaiting_date
User: "بكرة"
-> intent=provide_date
-> date_text="بكرة"
-> operation_type=null

stage=awaiting_time
User: "الساعة خمسة"
-> intent=provide_time
-> time_text="الساعة خمسة"
-> operation_type=null

INFORMATIONAL INTENTS
- ask_doctor:
  provider doctor catalog or doctor discovery.

- ask_service:
  actual services or service prices offered by the CURRENT
  provider.

- ask_available_slots:
  available appointment dates, times, or slots.

- ask_working_hours:
  provider, branch, or doctor working/opening hours.

- ask_provider:
  approved provider-specific knowledge such as provider
  information, policies, doctor expertise, or conditions
  treated by a specific doctor.

PROVIDER AND MEDICAL SCOPE
- MedMind does not diagnose conditions.
- Do not recommend medicines, creams, treatments,
  procedures, or home remedies.
- A symptom or condition is NOT automatically a specialty
  or service name.
- Do not invent specialty_name or service_name.

- If the user asks about the price/cost/fee of something they
  explicitly named, treat that named phrase as service_name.
  This is not inventing; it is extracting the user's own phrase.

- Price questions should use ask_service.
  Extract service_name when the user mentions a specific service,
  procedure, treatment, or named offering.
  Extract specialty_name when the user asks about prices for a
  specialty category.

Examples:

User: "تساقط الشعر بكام؟"
-> intent=ask_service
-> service_name="تساقط الشعر"

User: "سعر علاج تساقط الشعر كام؟"
-> intent=ask_service
-> service_name="علاج تساقط الشعر"

User: "حقن البلازما للشعر بكام؟"
-> intent=ask_service
-> service_name="حقن البلازما للشعر"

User: "سعر الليزر كام؟"
-> intent=ask_service
-> service_name="الليزر"

User: "أسعار خدمات الجلدية؟"
-> intent=ask_service
-> specialty_name="جلدية"

User: "أسعار الخدمات؟"
-> intent=ask_service
-> do not invent service_name

If the user describes a concern or goal and asks what the
CURRENT provider offers, use ask_service.

Examples:

User: "عايزة حاجة للتصبغات عندكم"
-> intent=ask_service
-> do not invent service_name

User: "عندكم خدمات للتصبغات؟"
-> intent=ask_service

User: "What services do you offer for pigmentation?"
-> intent=ask_service

Provider-specific knowledge:

User: "دكتور ماهر بيعالج حب الشباب؟"
-> intent=ask_provider

User: "What is Dr. Maher specialized in?"
-> intent=ask_provider

DOCTOR DISCOVERY
Use ask_doctor for doctor catalog/discovery questions.

Examples:

"مين دكاترة الجلدية عندكم؟"
-> intent=ask_doctor

"Which dermatologists do you have?"
-> intent=ask_doctor

Do not use ask_doctor merely because a doctor-specific
medical expertise question was asked.

AVAILABLE SLOTS VS WORKING HOURS
Use ask_available_slots for appointment availability.

"في مواعيد الخميس؟"
-> intent=ask_available_slots

"دكتور ماهر فاضي امتى؟"
-> intent=ask_available_slots

Use ask_working_hours only for working/opening hours.

"العيادة بتفتح امتى؟"
-> intent=ask_working_hours

"دكتور ماهر بيشتغل امتى؟"
-> intent=ask_working_hours

ENTITIES
Extract ONLY values explicitly provided or selected in the
CURRENT user message.

Never invent:
- specialty_name
- doctor_name
- service_name
- date_text
- time_text
- patient_name
- phone
- national_id
- appointment_reference

Never invent or resolve database UUIDs.
Those are resolved later by deterministic workflows and MCP.

CONFIRMATION
Use confirm_action or deny_action only when context shows
that confirmation is currently pending.

stage=awaiting_confirmation
User: "أيوه"
-> intent=confirm_action
-> confirmation=yes

A general word such as "تمام" is not automatically a
confirmation without confirmation context.

CORRECTIONS DURING CONFIRMATION
If confirmation is pending and the user supplies replacement
data, treat it as a correction rather than a simple rejection.

Example:

User: "لا الاسم الصح آية محمد"
-> intent=provide_patient_name
-> patient_name="آية محمد"
-> confirmation=unknown

User:
"لا الدكتور دكتورة منى والميعاد الجمعة الساعة خمسة"
-> doctor_name="دكتورة منى"
-> date_text="الجمعة"
-> time_text="الساعة خمسة"
-> confirmation=unknown

Extract all replacement values provided in the current turn.

Only use:
intent=deny_action
confirmation=no

when the user rejects the pending action and supplies no
replacement information.

Do not copy unchanged values from session state into entities.
""".strip()

# ============================================================
# LLM NLU
# ============================================================

class LLMNLU:

    def __init__(
        self,
        *,
        model: ChatOpenAI,
    ) -> None:

        self.model = model

        # OpenAI structured output
        self.structured_model = (
            model.with_structured_output(
                NLUResult,
                method="json_schema",
            )
        )

    # ========================================================
    # BUILD CONTEXT
    # ========================================================

    def _build_context(
        self,
        *,
        language: str,
        state: SessionState,
        history: list[ChatMessage],
        message: str,
    ) -> str:

        system_prompt = NLU_INSTRUCTIONS

        context_title = "CURRENT SESSION STATE"
        history_title = "RECENT CONVERSATION"
        message_title = "CURRENT USER MESSAGE"

        # ----------------------------------------------------
        # Structured state
        # ----------------------------------------------------

        state_data = (
            state.safe_llm_context()
        )

        state_json = json.dumps(
            state_data,
            ensure_ascii=False,
            indent=2,
        )

        # ----------------------------------------------------
        # Recent conversation
        # ----------------------------------------------------

        recent_history = (
            history[-6:]
        )

        history_lines = []

        for item in recent_history:

            history_lines.append(
                f"{item.role}: "
                f"{item.content}"
            )

        history_text = "\n".join(
            history_lines
        )

        if not history_text:

            history_text = (
                "(no previous messages)"
            )

        # ----------------------------------------------------
        # Final prompt
        # ----------------------------------------------------

        return (
            system_prompt
            + "\n\n"
            + "=" * 60
            + "\n"
            + context_title
            + "\n"
            + "=" * 60
            + "\n"
            + state_json
            + "\n\n"
            + "=" * 60
            + "\n"
            + history_title
            + "\n"
            + "=" * 60
            + "\n"
            + history_text
            + "\n\n"
            + "=" * 60
            + "\n"
            + message_title
            + "\n"
            + "=" * 60
            + "\n"
            + message
        )

    # ========================================================
    # UNDERSTAND
    # ========================================================

    async def understand(
        self,
        *,
        message: str,
        language: str,
        state: SessionState,
        history: list[ChatMessage],
    ) -> NLUResult:

        prompt = self._build_context(
            language=language,
            state=state,
            history=history,
            message=message,
        )

        result = await (
            self.structured_model
            .ainvoke(
                prompt
            )
        )

        if not isinstance(
            result,
            NLUResult,
        ):

            raise RuntimeError(
                "NLU did not return NLUResult."
            )

        return result
