from __future__ import annotations

from decimal import Decimal
from uuid import (
    UUID,
    uuid4,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lab_report import (
    LabReport,
)
from app.models.lab_result import (
    LabResult,
)


class LabRepository:

    def __init__(
        self,
        session: Session,
    ) -> None:

        self.session = session

    # ========================================================
    # CREATE REPORT
    # ========================================================

    def create_report(
        self,
        *,
        provider_id: UUID,
        diagnostic_attachment_id: UUID,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
        document_type: str | None = None,
        unreadable_fields_json: str | None = None,
        status: str = "pending",
    ) -> LabReport:

        report = LabReport(
            id=uuid4(),
            patient_id=patient_id,
            provider_id=provider_id,
            encounter_id=encounter_id,
            diagnostic_attachment_id=(
                diagnostic_attachment_id
            ),
            document_type=document_type,
            unreadable_fields_json=(
                unreadable_fields_json
            ),
            status=status,
        )

        self.session.add(
            report
        )

        self.session.flush()

        return report

    # ========================================================
    # CREATE RESULT
    # ========================================================

    def create_result(
        self,
        *,
        lab_report_id: UUID,
        result_index: int,
        raw_name: str,
        flag: str,
        mapping_status: str,
        panel: str | None = None,
        canonical_name: str | None = None,
        value: Decimal | None = None,
        unit: str | None = None,
        reference_min: Decimal | None = None,
        reference_max: Decimal | None = None,
        reference_text: str | None = None,
    ) -> LabResult:

        result = LabResult(
            id=uuid4(),
            lab_report_id=lab_report_id,
            result_index=result_index,
            panel=panel,
            raw_name=raw_name,
            canonical_name=canonical_name,
            value=value,
            unit=unit,
            reference_min=reference_min,
            reference_max=reference_max,
            reference_text=reference_text,
            flag=flag,
            mapping_status=mapping_status,
        )

        self.session.add(
            result
        )

        self.session.flush()

        return result

    # ========================================================
    # TENANT-SCOPED REPORT LOOKUP
    # ========================================================

    def get_report_by_attachment(
        self,
        *,
        provider_id: UUID,
        diagnostic_attachment_id: UUID,
    ) -> LabReport | None:

        statement = (
            select(
                LabReport
            )
            .where(
                LabReport.provider_id
                == provider_id,

                LabReport.diagnostic_attachment_id
                == diagnostic_attachment_id,
            )
        )

        return self.session.scalar(
            statement
        )

    # ========================================================
    # BIND REPORT TO PATIENT
    # ========================================================

    def bind_report_to_patient(
        self,
        *,
        report: LabReport,
        patient_id: UUID,
    ) -> LabReport:

        report.patient_id = patient_id

        self.session.flush()

        return report

    # ========================================================
    # BIND REPORT TO ENCOUNTER
    # ========================================================

    def bind_report_to_encounter(
        self,
        *,
        report: LabReport,
        encounter_id: UUID,
    ) -> LabReport:

        report.encounter_id = encounter_id

        self.session.flush()

        return report

    # ========================================================
    # UPDATE STATUS
    # ========================================================

    def set_report_status(
        self,
        *,
        report: LabReport,
        status: str,
    ) -> LabReport:

        report.status = status

        self.session.flush()

        return report