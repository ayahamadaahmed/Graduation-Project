from __future__ import annotations

import json

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.models.lab_report import (
    LabReport,
)

from app.repositories.lab_repository import (
    LabRepository,
)


# ============================================================
# INPUT CONTRACT
# ============================================================

@dataclass(
    frozen=True,
    slots=True,
)
class LabResultPersistenceInput:

    result_index: int

    raw_name: str

    flag: str

    mapping_status: str

    panel: str | None = None

    canonical_name: str | None = None

    value: Decimal | None = None

    unit: str | None = None

    reference_min: Decimal | None = None

    reference_max: Decimal | None = None

    reference_text: str | None = None


# ============================================================
# ERRORS
# ============================================================

class LabPersistenceError(
    RuntimeError
):
    pass


# ============================================================
# SERVICE
# ============================================================

class LabPersistenceService:

    def __init__(
        self,
        repository: LabRepository,
    ) -> None:

        self.repository = repository

    # ========================================================
    # SAVE PROCESSED LAB REPORT
    # ========================================================

    def save_processed_report(
        self,
        *,
        provider_id: UUID,
        diagnostic_attachment_id: UUID,
        document_type: str | None,
        results: list[
            LabResultPersistenceInput
        ],
        unreadable_fields: list[str] | None = None,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
    ) -> LabReport:

        # ----------------------------------------------------
        # Basic validation before touching DB.
        # ----------------------------------------------------

        if not results:
            raise LabPersistenceError(
                "A processed lab report must contain "
                "at least one result."
            )

        seen_indexes: set[int] = set()

        for result in results:

            if result.result_index < 0:
                raise LabPersistenceError(
                    "result_index cannot be negative."
                )

            if result.result_index in seen_indexes:
                raise LabPersistenceError(
                    "Duplicate result_index in lab report."
                )

            seen_indexes.add(
                result.result_index
            )

            if not result.raw_name.strip():
                raise LabPersistenceError(
                    "raw_name cannot be empty."
                )

            if result.flag not in {
                "low",
                "normal",
                "high",
                "unknown",
            }:
                raise LabPersistenceError(
                    "Invalid lab result flag."
                )

            if result.mapping_status not in {
                "mapped",
                "unmapped",
                "unreadable",
            }:
                raise LabPersistenceError(
                    "Invalid lab result mapping status."
                )

        unreadable_fields_json = (
            json.dumps(
                unreadable_fields or [],
                ensure_ascii=False,
            )
        )

        # ----------------------------------------------------
        # One DB transaction:
        #
        # report
        # + all results
        # + final status
        # ----------------------------------------------------

        try:

            report = (
                self.repository
                .create_report(
                    provider_id=provider_id,
                    diagnostic_attachment_id=(
                        diagnostic_attachment_id
                    ),
                    patient_id=patient_id,
                    encounter_id=encounter_id,
                    document_type=(
                        document_type
                    ),
                    unreadable_fields_json=(
                        unreadable_fields_json
                    ),
                    status="processing",
                )
            )

            for result in results:

                self.repository.create_result(
                    lab_report_id=report.id,
                    result_index=(
                        result.result_index
                    ),
                    panel=result.panel,
                    raw_name=(
                        result.raw_name.strip()
                    ),
                    canonical_name=(
                        result.canonical_name
                    ),
                    value=result.value,
                    unit=result.unit,
                    reference_min=(
                        result.reference_min
                    ),
                    reference_max=(
                        result.reference_max
                    ),
                    reference_text=(
                        result.reference_text
                    ),
                    flag=result.flag,
                    mapping_status=(
                        result.mapping_status
                    ),
                )

            self.repository.set_report_status(
                report=report,
                status="processed",
            )

            self.repository.session.commit()

        except Exception as exc:

            self.repository.session.rollback()

            raise LabPersistenceError(
                "Failed to persist processed "
                "lab report."
            ) from exc

        return report