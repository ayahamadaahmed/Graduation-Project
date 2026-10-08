from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class DiagnosticAttachmentUploadResponse(
    BaseModel
):

    attachment_id: str = Field(
        min_length=32,
        max_length=32,
    )

    content_type: Literal[
        "image/jpeg",
        "image/png",
    ]

    size_bytes: int = Field(
        gt=0,
    )