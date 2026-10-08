from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.diagnostic_assessment import (
    DiagnosticAssessment,
)
from app.models.radiology_report import (
    RadiologyReport,
)


class RadiologyRepository:

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
        modality: str,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
        status: str = "pending",
    ) -> RadiologyReport:

        report = RadiologyReport(
            id=uuid4(),
            patient_id=patient_id,
            provider_id=provider_id,
            encounter_id=encounter_id,
            diagnostic_attachment_id=(
                diagnostic_attachment_id
            ),
            modality=modality,
            status=status,
        )

        self.session.add(
            report
        )

        self.session.flush()

        return report

    # ========================================================
    # CREATE ASSESSMENT
    # ========================================================

    def create_assessment(
        self,
        *,
        radiology_report_id: UUID,
        classification: str,
        probabilities_json: str,
        confidence: Decimal,
        inference_latency_ms: Decimal,
        model_name: str,
        model_version: str,
        limitations_json: str,
        assessment_type: str = "radiology_model",
    ) -> DiagnosticAssessment:

        assessment = DiagnosticAssessment(
            id=uuid4(),
            radiology_report_id=(
                radiology_report_id
            ),
            assessment_type=(
                assessment_type
            ),
            classification=(
                classification
            ),
            probabilities_json=(
                probabilities_json
            ),
            confidence=confidence,
            inference_latency_ms=(
                inference_latency_ms
            ),
            model_name=model_name,
            model_version=model_version,
            limitations_json=(
                limitations_json
            ),
        )

        self.session.add(
            assessment
        )

        self.session.flush()

        return assessment

    # ========================================================
    # TENANT-SCOPED REPORT LOOKUP
    # ========================================================

    def get_report_by_attachment(
        self,
        *,
        provider_id: UUID,
        diagnostic_attachment_id: UUID,
    ) -> RadiologyReport | None:

        statement = (
            select(
                RadiologyReport
            )
            .where(
                RadiologyReport.provider_id
                == provider_id,

                RadiologyReport
                .diagnostic_attachment_id
                == diagnostic_attachment_id,
            )
        )

        return self.session.scalar(
            statement
        )

    # ========================================================
    # BIND TO PATIENT
    # ========================================================

    def bind_report_to_patient(
        self,
        *,
        report: RadiologyReport,
        patient_id: UUID,
    ) -> RadiologyReport:

        report.patient_id = patient_id

        self.session.flush()

        return report

    # ========================================================
    # BIND TO ENCOUNTER
    # ========================================================

    def bind_report_to_encounter(
        self,
        *,
        report: RadiologyReport,
        encounter_id: UUID,
    ) -> RadiologyReport:

        report.encounter_id = (
            encounter_id
        )

        self.session.flush()

        return report

    # ========================================================
    # UPDATE STATUS
    # ========================================================

    def set_report_status(
        self,
        *,
        report: RadiologyReport,
        status: str,
    ) -> RadiologyReport:

        report.status = status

        self.session.flush()

        return report