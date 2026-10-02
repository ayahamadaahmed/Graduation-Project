from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    Field,
)


class WorkflowResult(
    BaseModel
):

    handled: bool = True

    reply: str

    response_type: str

    data: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )