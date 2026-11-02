import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from pydantic import ValidationError
from fastapi import HTTPException

from app.schemas.ai_chat import AIChatRequest
from app.schemas.diagnostic_case import DiagnosticCaseSaveRequest
from app.api.routers.diagnostics import save_diagnostic_case, list_diagnostic_cases


def test_structured_symptom_answers_accept_supported_fields():
    request = AIChatRequest(
        session_id="session-1",
        message="إجاباتي على الأسئلة",
        channel="web",
        form_answers={
            "symptoms": "صداع",
            "onset": "منذ أيام",
            "severity": 4,
            "pattern": "تأتي وتختفي",
        },
    )

    assert request.form_answers["severity"] == 4


@pytest.mark.parametrize(
    "answers",
    [
        {"unknown": "value"},
        {"severity": 11},
        {"severity": True},
        {"onset": "غير موجود"},
        {"pattern": "غير موجود"},
    ],
)
def test_symptom_answers_reject_unsupported_values(answers):
    with pytest.raises(ValidationError):
        AIChatRequest(
            session_id="session-1",
            message="إجاباتي",
            channel="web",
            form_answers=answers,
        )


def test_saved_case_summary_requires_clinical_sections():
    request = DiagnosticCaseSaveRequest(
        complaint="صداع منذ يومين",
        summary={
            "patient_complaint": "صداع منذ يومين",
            "findings": [{"filename": "report.pdf", "value": "..."}],
            "observations": ["حقل واحد غير مقروء"],
            "impression": "ملخص المراجعة",
            "limitations": ["مراجعة الطبيب لازمة"],
            "sources": [{"filename": "report.pdf", "attachment_id": "a" * 32}],
        },
    )

    assert request.summary is not None
    assert request.summary.findings[0]["filename"] == "report.pdf"


def test_case_summary_rejects_unstructured_text_shape():
    with pytest.raises(ValidationError):
        DiagnosticCaseSaveRequest(
            complaint="شكوى",
            summary={"text": "ملخص نصي فقط"},
        )


class FakeCaseSession:
    def __init__(self):
        self.case = None

    def scalar(self, _statement):
        return self.case

    def add(self, case):
        case.id = uuid4()
        case.created_at = datetime.now(timezone.utc)
        case.updated_at = case.created_at
        self.case = case

    def commit(self):
        self.case.updated_at = datetime.now(timezone.utc)

    def refresh(self, _case):
        return None

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: [self.case] if self.case else [])


class FakeCaseBinding:
    def __init__(self, patient_id):
        self.patient_id = patient_id

    def resolve(self, *, provider_id, patient_id=None, encounter_id=None):
        assert provider_id is not None
        if patient_id and patient_id != self.patient_id:
            from app.services.diagnostic_attachment_binding_service import DiagnosticPatientProviderMismatchError
            raise DiagnosticPatientProviderMismatchError()
        return SimpleNamespace(patient_id=patient_id, encounter_id=encounter_id)


def test_case_save_and_history_round_trip():
    provider_id, patient_id = uuid4(), uuid4()
    session = FakeCaseSession()
    provider = SimpleNamespace(id=provider_id)
    payload = DiagnosticCaseSaveRequest(
        complaint="صداع منذ يومين",
        patient_id=patient_id,
        answers={"intake": {"severity": 4}},
        summary={
            "patient_complaint": "صداع منذ يومين",
            "findings": [{"filename": "report.pdf", "value": "12"}],
            "observations": [],
            "impression": "نتيجة للمراجعة",
            "limitations": ["ليست تشخيصًا نهائيًا"],
            "sources": [{"filename": "report.pdf", "attachment_id": "a" * 32}],
        },
    )

    saved = save_diagnostic_case(
        session_id="case-1", payload=payload, provider=provider,
        session=session, binding_service=FakeCaseBinding(patient_id),
    )
    history = list_diagnostic_cases(patient_id=patient_id, provider=provider, session=session)

    assert saved.status == "complete"
    assert saved.summary is not None and saved.summary.findings[0]["filename"] == "report.pdf"
    assert len(history) == 1 and history[0].answers["intake"]["severity"] == 4


def test_case_cannot_be_rebound_to_a_different_patient():
    provider_id, patient_id = uuid4(), uuid4()
    session = FakeCaseSession()
    provider = SimpleNamespace(id=provider_id)
    base_payload = DiagnosticCaseSaveRequest(patient_id=patient_id, complaint="شكوى")
    save_diagnostic_case(
        session_id="case-1", payload=base_payload, provider=provider,
        session=session, binding_service=FakeCaseBinding(patient_id),
    )
    with pytest.raises(HTTPException) as error:
        save_diagnostic_case(
            session_id="case-1",
            payload=DiagnosticCaseSaveRequest(patient_id=uuid4(), complaint="شكوى أخرى"),
            provider=provider,
            session=session,
            binding_service=FakeCaseBinding(patient_id),
        )
    assert error.value.status_code == 404
