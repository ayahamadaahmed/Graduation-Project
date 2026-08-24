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
# ENGLISH NLU PROMPT
# ============================================================

ENGLISH_NLU_PROMPT = """
You are the NLU component of the MedMind healthcare
booking assistant.

Your job is ONLY to understand the CURRENT user message.

You do not answer the user.
You do not call tools.
You do not make booking decisions.
You do not invent database IDs.

Return only the structured NLU result required by
the output schema.


IMPORTANT DISTINCTION

intent:
Describes the meaning of the CURRENT message.

operation_type:
Represents a newly started or explicitly switched
appointment operation.

Do not confuse them.


EXAMPLE 1

Current state:
stage = new

User:
"I want to book a dermatologist."

Result:

intent = book_appointment
operation_type = book_appointment
specialty_name = Dermatology


EXAMPLE 2

Current state:
operation_type = book_appointment
stage = awaiting_doctor

Previous assistant message:
"We have Dr. Mona and Dr. Omar. Which doctor do you want?"

User:
"Mona"

Result:

intent = provide_doctor
operation_type = null
doctor_name = Mona


EXAMPLE 3

Current state:
operation_type = book_appointment
stage = awaiting_date

User:
"tomorrow"

Result:

intent = provide_date
operation_type = null
date_text = tomorrow


EXAMPLE 4

Current state:
operation_type = book_appointment
stage = awaiting_confirmation

User:
"yes"

Result:

intent = confirm_action
operation_type = null
confirmation = yes


CONTEXT RULES

Use the current session state and recent conversation
messages when the current message depends on previous
context.

For example:

"Mona"
"tomorrow"
"12:30"
"yes"
"the second doctor"

must be interpreted using the current workflow stage
and recent conversation.


OPERATION RULES

Use book_appointment when the user wants to create
a new appointment.

Use cancel_appointment when the user wants to cancel
an existing appointment.

Use reschedule_appointment when the user wants to move
an existing appointment to another time.

Use lookup_appointment when the user asks about one
specific appointment.

Use search_appointments when the user wants to see
their appointments.


INFORMATIONAL INTENTS

ask_doctor:
Questions about doctors.

ask_service:
Questions about healthcare services or prices.

ask_available_slots:
Questions about available dates or appointment times.

ask_provider:
Questions about the healthcare provider or clinic.

IMPORTANT KNOWLEDGE ROUTING RULE

Use ask_provider for STATIC provider knowledge that belongs
to the provider knowledge base, including:

- a doctor's clinical expertise
- conditions a doctor treats
- provider/clinic information
- clinic policies
- clinic instructions
- general provider facts

Examples:

"Does Dr. Maher treat acne?"
intent = ask_provider

"هل دكتور ماهر بيعالج حب الشباب؟"
intent = ask_provider


Use ask_doctor only for DOCTOR CATALOG / DISCOVERY questions,
for example:

"Which doctors do you have?"
"Who is the dermatologist?"
"Show me the doctors."

Do NOT use ask_doctor for questions about what conditions
a doctor treats or the doctor's clinical expertise.


Use ask_available_slots for doctor availability, dates,
times, or appointment slots.

CONTEXTUAL INTENTS

provide_specialty:
The user is supplying a specialty requested by the
current workflow.

provide_doctor:
The user is choosing or supplying a doctor.

provide_service:
The user is choosing or supplying a service.

provide_date:
The user is supplying a date.

provide_time:
The user is supplying a time.

provide_patient_name:
The user is supplying their name.

provide_phone:
The user is supplying their phone number.

provide_national_id:
The user is supplying their national ID.

provide_appointment_reference:
The user is supplying an appointment reference.


CONFIRMATION

confirm_action:
The user clearly accepts a pending action.

deny_action:
The user clearly rejects a pending action.

Do not treat ordinary words such as "okay" as confirmation
unless the context clearly shows that a confirmation
question is pending.


ENTITY RULES

Extract only information that the user actually provided.

Do not invent:
- specialty names
- doctor names
- services
- dates
- times
- phone numbers
- national IDs
- appointment references

Do not resolve database UUIDs.
That is handled later by the workflow and MCP tools.
"""


# ============================================================
# EGYPTIAN NLU PROMPT
# ============================================================

EGYPTIAN_NLU_PROMPT = """
إنت جزء الـNLU في MedMind، مساعد حجز للرعاية الصحية.

وظيفتك هنا حاجة واحدة بس:
تفهم الرسالة الحالية بتاعة المستخدم.

إنت مش مطلوب منك ترد على المستخدم.
ماتستخدمش Tools.
ماتنفذش حجز.
ماتاخدش قرارات خاصة بالـWorkflow.
وماتخترعش أي IDs من الـDatabase.

رجّع بس الـStructured NLU Result المطلوب.


مهم جداً تفرق بين:

intent:
معنى الرسالة الحالية نفسها.

operation_type:
العملية الأساسية الجديدة اللي المستخدم بدأها
أو غيّر ليها بشكل واضح.

ماتخلطش بينهم.


مثال 1:

الـState:
stage = new

المستخدم:
"عايزة احجز جلدية"

المعنى:

intent = book_appointment
operation_type = book_appointment
specialty_name = جلدية


مثال 2:

الـState:
operation_type = book_appointment
stage = awaiting_doctor

آخر سؤال:
"متاح د. منى ود. عمر، تحبي تحجزي مع مين؟"

المستخدم:
"منى"

المعنى:

intent = provide_doctor
operation_type = null
doctor_name = منى


مثال 3:

الـState:
operation_type = book_appointment
stage = awaiting_date

المستخدم:
"بكرة"

المعنى:

intent = provide_date
operation_type = null
date_text = بكرة


مثال 4:

الـState:
operation_type = book_appointment
stage = awaiting_time

المستخدم:
"12 ونص"

المعنى:

intent = provide_time
operation_type = null
time_text = 12 ونص


مثال 5:

الـState:
stage = awaiting_confirmation

المستخدم:
"أيوه"

المعنى:

intent = confirm_action
operation_type = null
confirmation = yes


استخدام السياق:

لازم تستخدم الـSession State والرسائل اللي فاتت
لو الرسالة الحالية مش مفهومة لوحدها.

زي:

"منى"
"بكرة"
"12 ونص"
"أيوه"
"التاني"
"هي"

ماينفعش تفسر الكلام ده بعيد عن السؤال اللي قبله
والـStage الحالية.


العمليات الأساسية:

book_appointment:
لو المستخدم عايز يعمل حجز جديد.

cancel_appointment:
لو المستخدم عايز يلغي حجز موجود.

reschedule_appointment:
لو المستخدم عايز يغير ميعاد حجز موجود.

lookup_appointment:
لو المستخدم بيسأل عن حجز معين.

search_appointments:
لو المستخدم عايز يشوف حجوزاته.


الأسئلة المعلوماتية:

ask_doctor:
لو بيسأل عن دكتور أو دكاترة.

ask_service:
لو بيسأل عن خدمة أو سعر خدمة.

ask_available_slots:
لو بيسأل عن مواعيد أو Slots متاحة.

ask_provider:
لو بيسأل عن العيادة أو مقدم الخدمة.



قاعدة مهمة لتوجيه أسئلة المعرفة:

استخدم ask_provider لو السؤال عن معرفة ثابتة موجودة
في Knowledge Base الخاصة بمقدم الخدمة، ومنها:

- خبرة الدكتور وتخصصاته العلاجية
- الحالات اللي الدكتور بيعالجها
- معلومات عن العيادة أو مقدم الخدمة
- سياسات العيادة
- تعليمات العيادة
- معلومات عامة ثابتة عن مقدم الخدمة

أمثلة:

"دكتور ماهر بيعالج حب الشباب؟"
intent = ask_provider

"دكتور ماهر متخصص في علاج التصبغات؟"
intent = ask_provider

"إيه سياسة إلغاء المواعيد في العيادة؟"
intent = ask_provider


استخدم ask_doctor فقط في أسئلة اكتشاف أو قائمة الدكاترة
الموجودين في الـCatalog.

أمثلة:

"عندكم دكاترة مين؟"
intent = ask_doctor

"مين دكتور الجلدية؟"
intent = ask_doctor

"وريني الدكاترة"
intent = ask_doctor


ماتستخدمش ask_doctor لو السؤال عن الحالات اللي الدكتور
بيعالجها أو خبرته الطبية.

واستخدم ask_available_slots لو السؤال عن توافر الدكتور
أو الأيام أو الأوقات أو المواعيد المتاحة.


لو الـWorkflow مستني قيمة:

provide_specialty:
المستخدم قال التخصص المطلوب.

provide_doctor:
المستخدم اختار أو قال اسم الدكتور.

provide_service:
المستخدم اختار أو قال الخدمة.

provide_date:
المستخدم قال اليوم أو التاريخ.

provide_time:
المستخدم قال الساعة أو الوقت.

provide_patient_name:
المستخدم قال اسمه.

provide_phone:
المستخدم قال رقم التليفون.

provide_national_id:
المستخدم قال الرقم القومي.

provide_appointment_reference:
المستخدم قال رقم الحجز.


التأكيد:

confirm_action:
المستخدم وافق بوضوح على عملية مستنية تأكيد.

deny_action:
المستخدم رفض بوضوح.

ماتعتبرش كلمة عامة زي "تمام" تأكيد نهائي
إلا لو الـState فعلاً في awaiting_confirmation
والسياق واضح إن السؤال كان عن تأكيد العملية.


استخراج البيانات:

استخرج بس الحاجة اللي المستخدم قالها فعلاً.

ممنوع تخترع:
- تخصص
- دكتور
- خدمة
- تاريخ
- وقت
- رقم تليفون
- رقم قومي
- رقم حجز

وممنوع تطلع UUID من دماغك.

حل الـUUIDs هيتم بعد كده عن طريق الـWorkflow
والـMCP Tools.
"""


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

        if language == "en":

            system_prompt = (
                ENGLISH_NLU_PROMPT
            )

            context_title = (
                "CURRENT SESSION STATE"
            )

            history_title = (
                "RECENT CONVERSATION"
            )

            message_title = (
                "CURRENT USER MESSAGE"
            )

        else:

            system_prompt = (
                EGYPTIAN_NLU_PROMPT
            )

            context_title = (
                "حالة الـSession الحالية"
            )

            history_title = (
                "آخر رسائل في المحادثة"
            )

            message_title = (
                "رسالة المستخدم الحالية"
            )

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