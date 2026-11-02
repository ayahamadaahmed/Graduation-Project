from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from typing import Literal
from typing import Any
from uuid import UUID


class DiagnosticFormQuestion(BaseModel):
    id: str
    label: str
    type: Literal["text", "number", "select", "multi_select"]
    required: bool = False
    options: list[str] = Field(default_factory=list)
    minimum: int | None = None
    maximum: int | None = None


class DiagnosticInteractionForm(BaseModel):
    id: str
    title: str
    description: str
    questions: list[DiagnosticFormQuestion]

class AIChatContextMessage(BaseModel):

    role: Literal["user", "assistant"]

    content: str = Field(
        min_length=1,
        max_length=5000,
    )


class AIChatRequest(BaseModel):

    session_id: str = Field(
        min_length=1,
        max_length=128,
    )

    patient_id: UUID | None = None

    message: str = Field(
        min_length=1,
        max_length=4000,
    )

    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ] 

    diagnostic_mode: Literal[
        "auto_image",
    ] | None = None

    attachment_ids: list[str] = Field(
        default_factory=list,
    )

    conversation_context: list[AIChatContextMessage] = Field(
        default_factory=list,
        max_length=24,
    )

    form_answers: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conversation_context")
    @classmethod
    def validate_conversation_context(
        cls,
        values: list[AIChatContextMessage],
    ) -> list[AIChatContextMessage]:
        total_chars = sum(len(item.content) for item in values)
        if total_chars > 60000:
            raise ValueError("conversation_context is too large.")
        return values

    @field_validator("form_answers")
    @classmethod
    def validate_form_answers(cls, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {"symptoms", "onset", "severity", "pattern"}
        if not set(values).issubset(allowed):
            raise ValueError("form_answers contains an unsupported field.")
        if sum(len(str(value)) for value in values.values()) > 4000:
            raise ValueError("form_answers is too large.")
        if "symptoms" in values and not isinstance(values["symptoms"], str):
            raise ValueError("symptoms must be text.")
        if "onset" in values and values["onset"] not in {"اليوم", "منذ أيام", "منذ أسابيع", "منذ أشهر", "غير متأكد"}:
            raise ValueError("onset has an unsupported option.")
        if "pattern" in values and values["pattern"] not in {"تتحسن", "ثابتة", "تزداد", "تأتي وتختفي", "غير متأكد"}:
            raise ValueError("pattern has an unsupported option.")
        if "severity" in values and (
            isinstance(values["severity"], bool)
            or not isinstance(values["severity"], int)
            or not 0 <= values["severity"] <= 10
        ):
            raise ValueError("severity must be an integer from 0 to 10.")
        return values

    @field_validator(
        "session_id",
        "message",
    )
    @classmethod
    def strip_text(
        cls,
        value: str,
    ) -> str:

        value = value.strip()

        if not value:
            raise ValueError(
                "Value cannot be empty."
            )

        return value

    @field_validator(
        "attachment_ids",
    )
    @classmethod
    def strip_attachment_ids(
        cls,
        values: list[str],
    ) -> list[str]:

        if len(values) > 10:
            raise ValueError("At most 10 attachments are allowed per message.")

        normalized: list[str] = []

        for value in values:

            value = value.strip()

            if not value:
                raise ValueError(
                    "attachment_ids cannot "
                    "contain empty values."
                )

            normalized.append(
                value
            )

        return normalized    


class AIChatResponse(BaseModel):

    session_id: str

    reply: str

    interaction_form: DiagnosticInteractionForm | None = None

    diagnostic_result: dict[str, Any] | None = None

    diagnostic_results: list[dict[str, Any]] = Field(default_factory=list)

    diagnostic_file_replies: list[dict[str, Any]] = Field(default_factory=list)

    stage: str

    intent: str | None = None

    language: str | None = None

    awaiting_confirmation: bool = False

    appointment_reference: str | None = None

    error_code: str | None = None
    
    nlu_source: str | None = None

    nlu_provider: str | None = None

    operation_id: str | None = None

    operation_type: str | None = None

    operation_status: str | None = None
    
    # -----------------------------
    # NLG observability
    # -----------------------------

    response_type: str | None = None
    route: str | None = None
    nlg_source: str | None = None

    nlg_guard_passed: bool | None = None

    nlg_violations: list[str] = Field(
        default_factory=list,
    )

    nlg_fallback_reason: str | None = None
