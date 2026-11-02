from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiagnosticCaseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_complaint: str = Field(default="", max_length=4000)
    findings: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    observations: list[str] = Field(default_factory=list, max_length=200)
    impression: str = Field(default="", max_length=10000)
    next_steps: str = Field(default="", max_length=10000)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class DiagnosticCaseSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complaint: str = Field(default="", max_length=4000)
    answers: dict[str, Any] = Field(default_factory=dict)
    summary: DiagnosticCaseSummary | None = None
    patient_id: UUID | None = None
    encounter_id: UUID | None = None

    @field_validator("answers")
    @classmethod
    def limit_answers_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 80000:
            raise ValueError("Case answers exceed 80 KB.")
        return value

    @field_validator("summary")
    @classmethod
    def limit_summary_size(cls, value: DiagnosticCaseSummary | None) -> DiagnosticCaseSummary | None:
        if value is not None and len(value.model_dump_json()) > 50000:
            raise ValueError("Case summary exceeds 50 KB.")
        return value


class DiagnosticCaseResponse(BaseModel):
    id: UUID
    session_id: str
    patient_id: UUID | None
    encounter_id: UUID | None
    complaint: str
    answers: dict[str, Any]
    summary: DiagnosticCaseSummary | None
    status: str
    created_at: datetime
    updated_at: datetime
