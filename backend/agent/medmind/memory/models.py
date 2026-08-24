from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class ChatMessage(
    BaseModel
):

    role: Literal[
        "user",
        "assistant",
    ]

    content: str

    created_at: datetime = Field(
        default_factory=lambda:
            datetime.now(
                timezone.utc
            )
    )