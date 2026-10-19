"""Staff-only appointment reads: auth, role/doctor/lab scope, provider isolation, audit (no database)."""

from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import appointments
from app.repositories.appointment_repository import AppointmentRepository
from app.security.staff_context import StaffContext
from app.services.appointment_service import AppointmentService

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
PROVIDER_A, PROVIDER_B = uuid4(), uuid4()
DOCTOR_1, DOCTOR_2 = uuid4(), uuid4()
PATIENT = uuid4()


def _row(reference, provider_id, doctor_id, service_type):
    return {
        "id": uuid4(), "provider_id": provider_id, "appointment_reference": reference,
        "patient_id": PATIENT, "patient_name": "P", "phone": "01000000000", "slot_id": uuid4(),
        "doctor_id": doctor_id, "branch_id": uuid4(), "service_id": uuid4(),
        "scheduled_date": date(2026, 10, 20), "start_time": time(10), "end_time": time(10, 15),
        "channel": "voice", "status": "confirmed", "notes": None, "confirmed_at": NOW,
        "created_at": NOW, "updated_at": NOW, "created_by_type": "ai_agent",
        "created_by_reference": None, "reschedule_count": 0,
        "_service_type": service_type,
    }


ROWS = [
    _row("APT-DOC1", PROVIDER_A, DOCTOR_1, "consultation"),
    _row("APT-DOC2", PROVIDER_A, DOCTOR_2, "consultation"),
    _row("APT-LAB", PROVIDER_A, None, "diagnostic"),
    _row("APT-OTHER", PROVIDER_B, DOCTOR_1, "diagnostic"),
]


class FakeRepository:
    """Applies the same provider + scope filters as the real SQL."""

    def __init__(self):
        self.calls = []

    def _match(self, row, provider_id, scope_doctor_id, scope_service_type):
        return (
            row["provider_id"] == provider_id
            and (scope_doctor_id is None or row["doctor_id"] == scope_doctor_id)
            and (scope_service_type is None or row["_service_type"] == scope_service_type)
        )

    @staticmethod
    def _public(row):
        return {k: v for k, v in row.items() if not k.startswith("_")}

    def get_appointment_by_reference(self, *, provider_id, appointment_reference,
                                     scope_doctor_id=None, scope_service_type=None):
        self.calls.append(("ref", provider_id, scope_doctor_id, scope_service_type))
        for row in ROWS:
            if row["appointment_reference"] == appointment_reference and self._match(
                row, provider_id, scope_doctor_id, scope_service_type
            ):
                return self._public(row)
        return None

    def get_patient_for_provider(self, *, provider_id, patient_id):
        return SimpleNamespace(id=patient_id) if provider_id == PROVIDER_A and patient_id == PATIENT else None

    def list_appointments_by_patient(self, *, provider_id, patient_id, include_cancelled, limit,
                                     scope_doctor_id=None, scope_service_type=None):
        self.calls.append(("list", provider_id, scope_doctor_id, scope_service_type))
        return [
            self._public(r) for r in ROWS
            if r["patient_id"] == patient_id and self._match(r, provider_id, scope_doctor_id, scope_service_type)
        ]


class StubAudit:
    def __init__(self):
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)


def _staff(role, provider_id=PROVIDER_A, doctor_id=None):
    return StaffContext(user_id=uuid4(), membership_id=uuid4(), provider_id=provider_id,
                        role=role, doctor_id=doctor_id)


def _client(staff=None):
    repo, audit = FakeRepository(), StubAudit()
    service = AppointmentService.__new__(AppointmentService)
    service.repository = repo
    app = FastAPI()
    app.include_router(appointments.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=staff.provider_id if staff else PROVIDER_A
    )
    app.dependency_overrides[deps.get_appointment_service] = lambda: service
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: audit
    if staff is None:
        app.dependency_overrides[deps.get_staff_access_service] = lambda: object()
    else:
        app.dependency_overrides[deps.get_current_staff] = lambda: staff
    return TestClient(app), repo, audit


def _ref(client, reference):
    return client.get(f"/api/v1/appointments/reference/{reference}")


def _list(client):
    return client.get(f"/api/v1/appointments/patient/{PATIENT}", params={"include_cancelled": True})


def _refs(response):
    return sorted(a["appointment_reference"] for a in response.json()["appointments"])


# ---------------------------------------------------------------- authentication


def test_reads_require_staff_token():
    client, repo, audit = _client(staff=None)
    assert _ref(client, "APT-DOC1").status_code == 401
    assert _list(client).status_code == 401
    assert not repo.calls and not audit.records


# ---------------------------------------------------------------- provider-wide roles


@pytest.mark.parametrize("role", ["provider_admin", "receptionist"])
def test_provider_wide_roles_read_any_appointment_of_provider(role):
    client, repo, audit = _client(_staff(role))
    for reference in ("APT-DOC1", "APT-DOC2", "APT-LAB"):
        assert _ref(client, reference).status_code == 200
    listed = _list(client)
    assert listed.status_code == 200
    assert _refs(listed) == ["APT-DOC1", "APT-DOC2", "APT-LAB"]
    assert all(call[2] is None and call[3] is None for call in repo.calls)


# ---------------------------------------------------------------- doctor scope


def test_doctor_reads_only_own_appointments():
    client, repo, audit = _client(_staff("doctor", doctor_id=DOCTOR_1))
    assert _ref(client, "APT-DOC1").status_code == 200
    denied = _ref(client, "APT-DOC2")
    assert denied.status_code == 404
    assert denied.json()["detail"]["code"] == "APPOINTMENT_NOT_FOUND"
    assert _ref(client, "APT-LAB").status_code == 404
    assert _refs(_list(client)) == ["APT-DOC1"]
    assert all(call[2] == DOCTOR_1 for call in repo.calls)


def test_doctor_without_doctor_identity_is_denied():
    client, repo, audit = _client(_staff("doctor", doctor_id=None))
    assert _ref(client, "APT-DOC1").status_code == 403
    assert _list(client).status_code == 403
    assert not repo.calls and not audit.records


# ---------------------------------------------------------------- lab scope


def test_lab_staff_reads_only_lab_appointments():
    client, repo, audit = _client(_staff("lab_staff"))
    assert _ref(client, "APT-LAB").status_code == 200
    assert _ref(client, "APT-DOC1").status_code == 404
    assert _refs(_list(client)) == ["APT-LAB"]
    assert all(call[3] == "diagnostic" for call in repo.calls)


# ---------------------------------------------------------------- unknown role


def test_unknown_role_is_denied_by_router_and_service():
    client, repo, audit = _client(_staff("pharmacist"))
    assert _ref(client, "APT-DOC1").status_code == 403
    service = AppointmentService.__new__(AppointmentService)
    service.repository = FakeRepository()
    with pytest.raises(Exception) as exc_info:
        service.get_booking_by_reference_for_staff(staff=_staff("pharmacist"), appointment_reference="APT-DOC1")
    assert exc_info.value.status_code == 403
    assert not service.repository.calls


# ---------------------------------------------------------------- provider isolation


def test_other_providers_appointment_is_not_found():
    client, repo, audit = _client(_staff("provider_admin"))
    response = _ref(client, "APT-OTHER")
    assert response.status_code == 404
    assert repo.calls == [("ref", PROVIDER_A, None, None)]


def test_other_providers_staff_cannot_list_patient():
    client, repo, audit = _client(_staff("provider_admin", provider_id=PROVIDER_B))
    response = _list(client)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PATIENT_NOT_FOUND_FOR_PROVIDER"
    assert not audit.records


# ---------------------------------------------------------------- audit


def test_successful_reads_are_audited_without_pii():
    staff = _staff("receptionist")
    client, repo, audit = _client(staff)
    _ref(client, "APT-DOC1")
    _list(client)
    _ref(client, "APT-OTHER")
    assert [r["action"] for r in audit.records] == ["appointment.read", "appointment.list_for_patient"]
    assert all(r["outcome"] == "success" and r["provider_id"] == PROVIDER_A for r in audit.records)
    assert all(r["membership_id"] == staff.membership_id for r in audit.records)
    assert audit.records[0]["resource_id"] == str(ROWS[0]["id"])
    assert "APT-DOC1" not in str(audit.records) and "01000000000" not in str(audit.records)


# ---------------------------------------------------------------- repository SQL


class CapturingSession:
    def __init__(self):
        self.sql, self.params = None, None

    def execute(self, statement, params):
        self.sql, self.params = str(statement), params
        return self

    def mappings(self):
        return self

    def first(self):
        return None

    def all(self):
        return []


def test_repository_sql_applies_scope_filters():
    session = CapturingSession()
    repo = AppointmentRepository(session)

    repo.get_appointment_by_reference(provider_id=PROVIDER_A, appointment_reference="APT-1",
                                      scope_doctor_id=DOCTOR_1)
    assert "OR appointment.doctor_id = :scope_doctor_id" in session.sql
    assert "OR service.service_type = :scope_service_type" in session.sql
    assert session.params["scope_doctor_id"] == str(DOCTOR_1)
    assert session.params["scope_service_type"] is None

    repo.list_appointments_by_patient(provider_id=PROVIDER_A, patient_id=PATIENT, include_cancelled=False,
                                      limit=10, scope_service_type="diagnostic")
    assert "OR appointment.doctor_id = :scope_doctor_id" in session.sql
    assert session.params["scope_doctor_id"] is None
    assert session.params["scope_service_type"] == "diagnostic"

    # Unscoped callers (patient /lookup, /search-by-national-id, post-call) keep no filter.
    repo.get_appointment_by_reference(provider_id=PROVIDER_A, appointment_reference="APT-1")
    assert session.params["scope_doctor_id"] is None and session.params["scope_service_type"] is None


# ---------------------------------------------------------------- patient flows untouched


def test_patient_flows_remain_unauthenticated_by_staff():
    spec = FastAPI()
    spec.include_router(appointments.router, prefix="/api/v1")
    paths = spec.openapi()["paths"]
    for path in ("/api/v1/appointments/lookup", "/api/v1/appointments/search-by-national-id"):
        assert "security" not in paths[path]["post"]
    for path in ("/api/v1/appointments/reference/{appointment_reference}",
                 "/api/v1/appointments/patient/{patient_id}"):
        assert paths[path]["get"]["security"] == [{"HTTPBearer": []}]
