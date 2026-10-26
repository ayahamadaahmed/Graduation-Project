from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import staff_ehr
from app.schemas.staff_ehr import (
    ClinicalNoteListResponse,
    ClinicalNoteOut,
    LabReportDetailResponse,
    MedicalHistoryResponse,
    RadiologyReportDetailResponse,
    ReportListResponse,
    VisitListResponse,
)
from app.security.staff_context import StaffContext

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
PROVIDER_ID = uuid4()
PATIENT_ID = uuid4()
NOTE_ID = uuid4()
REPORT_ID = uuid4()
ENCOUNTER_ID = uuid4()


# ============================================================
# STUBS
# ============================================================
class StubService:
    def __init__(self):
        self.calls = []
        self.raises = None

    def _go(self, name, **kwargs):
        self.calls.append((name, kwargs))

        if self.raises is not None:
            raise self.raises

    def get_medical_history(self, **kw):
        self._go("history", **kw)
        return MedicalHistoryResponse(patient_id=kw["patient_id"], conditions=[], allergies=[], medications=[])

    def list_visits(self, **kw):
        self._go("visits", **kw)
        return VisitListResponse(patient_id=kw["patient_id"], total=0, limit=kw["limit"], offset=kw["offset"], items=[])

    def list_reports(self, **kw):
        self._go("reports", **kw)
        return ReportListResponse(patient_id=kw["patient_id"], total=0, limit=kw["limit"], offset=kw["offset"], items=[])

    def get_lab_report(self, **kw):
        self._go("lab", **kw)
        return LabReportDetailResponse(
            report_id=kw["report_id"], patient_id=kw["patient_id"], status="processed",
            unreadable_fields=[], created_at=NOW, results=[],
        )

    def get_radiology_report(self, **kw):
        self._go("radiology", **kw)
        return RadiologyReportDetailResponse(
            report_id=kw["report_id"], patient_id=kw["patient_id"], modality="chest_xray",
            status="processed", created_at=NOW, assessments=[],
        )

    def _note(self, patient_id, note_id=NOTE_ID, status="draft"):
        return ClinicalNoteOut(
            note_id=note_id, patient_id=patient_id, encounter_id=ENCOUNTER_ID, doctor_id=uuid4(),
            note_type="progress", note_text="text", status=status, created_at=NOW, updated_at=NOW,
        )

    def list_notes(self, **kw):
        self._go("notes", **kw)
        return ClinicalNoteListResponse(patient_id=kw["patient_id"], total=0, limit=kw["limit"], offset=kw["offset"], items=[])

    def get_note(self, **kw):
        self._go("note", **kw)
        return self._note(kw["patient_id"], kw["note_id"])

    def create_note(self, **kw):
        self._go("create", **kw)
        return self._note(kw["patient_id"])

    def sign_note(self, **kw):
        self._go("sign", **kw)
        return self._note(kw["patient_id"], kw["note_id"], status="signed")


class RecordingAudit:
    def __init__(self):
        self.rows = []
        self.fail = False

    def record(self, **kwargs):
        if self.fail:
            raise RuntimeError("audit database down")

        self.rows.append(kwargs)


class Harness:
    def __init__(self):
        self.service = StubService()
        self.audit = RecordingAudit()
        self.role = "doctor"

        app = FastAPI()
        app.include_router(staff_ehr.router, prefix="/api/v1")

        app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(id=PROVIDER_ID)
        app.dependency_overrides[deps.get_current_staff] = self._staff
        app.dependency_overrides[deps.get_ehr_record_service] = lambda: self.service
        app.dependency_overrides[deps.get_staff_audit_service] = lambda: self.audit

        self.client = TestClient(app, raise_server_exceptions=False)

    def _staff(self):
        return StaffContext(
            user_id=uuid4(), membership_id=uuid4(), provider_id=PROVIDER_ID,
            role=self.role, doctor_id=uuid4() if self.role == "doctor" else None,
        )


@pytest.fixture
def h():
    return Harness()


BASE = f"/api/v1/staff/patients/{PATIENT_ID}"

# (method, path, allowed roles)
ENDPOINTS = [
    ("GET", f"{BASE}/medical-history", {"doctor"}),
    ("GET", f"{BASE}/visits", {"doctor"}),
    ("GET", f"{BASE}/reports", {"doctor", "lab_staff"}),
    ("GET", f"{BASE}/reports/lab/{REPORT_ID}", {"doctor", "lab_staff"}),
    ("GET", f"{BASE}/reports/radiology/{REPORT_ID}", {"doctor", "lab_staff"}),
    ("GET", f"{BASE}/clinical-notes", {"doctor"}),
    ("GET", f"{BASE}/clinical-notes/{NOTE_ID}", {"doctor"}),
    ("POST", f"{BASE}/clinical-notes", {"doctor"}),
    ("POST", f"{BASE}/clinical-notes/{NOTE_ID}/sign", {"doctor"}),
]

NOTE_BODY = {"encounter_id": str(ENCOUNTER_ID), "note_text": "Stable."}


def call(h, method, path):
    if method == "POST" and path.endswith("/clinical-notes"):
        return h.client.post(path, json=NOTE_BODY)

    return h.client.request(method, path)


# ============================================================
# ROLE MATRIX
# ============================================================
@pytest.mark.parametrize("method,path,allowed", ENDPOINTS)
@pytest.mark.parametrize("role", ["doctor", "lab_staff", "receptionist", "provider_admin"])
def test_role_matrix(h, method, path, allowed, role):
    h.role = role

    response = call(h, method, path)

    if role in allowed:
        assert response.status_code in (200, 201), response.text
    else:
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "STAFF_PERMISSION_DENIED"
        assert h.service.calls == []            # the service is never reached


# ============================================================
# AUDIT LOGGING
# ============================================================
def test_successful_read_is_audited(h):
    response = h.client.get(f"{BASE}/medical-history")

    assert response.status_code == 200
    row = h.audit.rows[0]
    assert row["action"] == "ehr.medical_history.read"
    assert row["outcome"] == "success"
    assert row["patient_id"] == PATIENT_ID
    assert row["provider_id"] == PROVIDER_ID


def test_report_and_note_reads_record_the_resource_id(h):
    h.client.get(f"{BASE}/reports/lab/{REPORT_ID}")
    h.client.get(f"{BASE}/clinical-notes/{NOTE_ID}")

    assert [r["resource_id"] for r in h.audit.rows] == [str(REPORT_ID), str(NOTE_ID)]
    assert [r["resource_type"] for r in h.audit.rows] == ["lab_report", "clinical_note"]


def test_creating_a_note_is_audited_with_the_new_note_id(h):
    response = h.client.post(f"{BASE}/clinical-notes", json=NOTE_BODY)

    assert response.status_code == 201
    row = h.audit.rows[0]
    assert row["action"] == "ehr.note.create"
    assert row["resource_id"] == str(NOTE_ID)
    assert row["outcome"] == "success"


@pytest.mark.parametrize(
    "status_code,outcome",
    [(404, "not_found"), (403, "denied"), (409, "error")],
)
def test_failed_access_is_audited_with_matching_outcome(h, status_code, outcome):
    h.service.raises = HTTPException(status_code=status_code, detail={"code": "X", "message": "m"})

    response = h.client.get(f"{BASE}/medical-history")

    assert response.status_code == status_code
    assert h.audit.rows[0]["outcome"] == outcome


def test_audit_failure_blocks_a_successful_read(h):
    h.audit.fail = True

    response = h.client.get(f"{BASE}/medical-history")

    assert response.status_code == 500            # fail closed: no clinical data without an audit trail


def test_audit_failure_does_not_hide_the_real_error(h):
    h.audit.fail = True
    h.service.raises = HTTPException(status_code=404, detail={"code": "PATIENT_NOT_FOUND", "message": "m"})

    response = h.client.get(f"{BASE}/medical-history")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PATIENT_NOT_FOUND"


# ============================================================
# TENANT / IDENTITY COMES FROM THE TOKEN
# ============================================================
def test_service_receives_the_token_identity_not_the_client_input(h):
    h.client.post(
        f"{BASE}/clinical-notes",
        json={**NOTE_BODY, "doctor_id": str(uuid4()), "provider_id": str(uuid4())},   # extra fields are ignored
    )

    name, kwargs = h.service.calls[0]

    assert name == "create"
    assert kwargs["staff"].provider_id == PROVIDER_ID
    assert not hasattr(kwargs["data"], "doctor_id")
    assert not hasattr(kwargs["data"], "provider_id")


# ============================================================
# VALIDATION
# ============================================================
@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "limit=abc"])
def test_pagination_bounds(h, query):
    for suffix in ("visits", "reports", "clinical-notes"):
        assert h.client.get(f"{BASE}/{suffix}?{query}").status_code == 422

    assert h.service.calls == []


def test_report_type_filter_is_validated(h):
    assert h.client.get(f"{BASE}/reports?report_type=mri").status_code == 422
    assert h.client.get(f"{BASE}/reports?report_type=lab").status_code == 200


def test_pagination_defaults(h):
    h.client.get(f"{BASE}/visits")

    _, kwargs = h.service.calls[0]
    assert (kwargs["limit"], kwargs["offset"]) == (50, 0)


@pytest.mark.parametrize(
    "body",
    [
        {},                                                                    # missing everything
        {"encounter_id": str(ENCOUNTER_ID)},                                   # missing text
        {"encounter_id": str(ENCOUNTER_ID), "note_text": "   "},               # blank text
        {"encounter_id": str(ENCOUNTER_ID), "note_text": "x" * 20001},         # too long
        {"encounter_id": "not-a-uuid", "note_text": "x"},                      # bad id
        {"encounter_id": str(ENCOUNTER_ID), "note_text": "x", "note_type": "poem"},
        {"encounter_id": str(ENCOUNTER_ID), "note_text": "x", "note_type": "addendum"},  # no target
        {"encounter_id": str(ENCOUNTER_ID), "note_text": "x", "addendum_to_note_id": str(NOTE_ID)},  # target on non-addendum
    ],
)
def test_create_note_validation(h, body):
    response = h.client.post(f"{BASE}/clinical-notes", json=body)

    assert response.status_code == 422
    assert h.service.calls == []


def test_non_uuid_path_ids_are_rejected(h):
    assert h.client.get("/api/v1/staff/patients/not-a-uuid/medical-history").status_code == 422
    assert h.client.get(f"{BASE}/clinical-notes/not-a-uuid").status_code == 422
