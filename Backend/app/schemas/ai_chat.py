from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from typing import Literal

class AIChatRequest(BaseModel):

    session_id: str = Field(
        min_length=1,
        max_length=128,
    )

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

    attachment_ids: list[str] = Field(
        default_factory=list,
    )

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

class AIChatSessionCreateRequest(BaseModel):
    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ]


class AIChatSessionCloseRequest(BaseModel):
    # Sent in the body (not the URL) so access logs never record it.
    session_id: str = Field(
        min_length=1,
        max_length=128,
    )


class AIChatSessionResponse(BaseModel):
    # Server-issued and unpredictable; the only valid session_id for /ai/chat.
    session_id: str

    channel: str

    idle_timeout_seconds: int
