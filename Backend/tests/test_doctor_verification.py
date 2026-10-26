"""Doctor verification workflow (2026-10-22).

- POST /admin/doctors/{id}/verification  {"decision": "verified"} or
  {"decision": "rejected", "reason": "..."}; POST /admin/doctors/{id}/resubmit.
  provider_admin of the doctor's provider only. Each real transition writes
  one doctor_verification_decisions row and one staff audit row in the same
  commit; repeats of an approval or resubmission are 200 no-ops; anything
  else not allowed is 409 DOCTOR_VERIFICATION_CONFLICT.
- With DOCTOR_VERIFICATION_ENFORCED=true (default false), catalog, search
  and booking accept only active AND verified doctors (DOCTOR_NOT_BOOKABLE
  for booking/rescheduling); lab slots without a doctor are unaffected.
- Migration c3d9e6a2f8b1 and the opt-in read-only report
  Database_latest/08_doctor_verification_status_report.sql are checked
  statically.

No database: repositories are fakes and SQL is compiled, never executed.
"""

import importlib.util
import inspect
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api import dependencies as deps
from app.api.routers import admin_catalog
from app.core.config import Settings, get_settings
from app.models import DoctorVerificationDecision
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.search_repository import SearchRepository
from app.schemas.admin_catalog import DoctorVerificationRequest
from app.schemas.appointment import AppointmentCreateRequest
from app.services import admin_catalog_service as admin_service_module
from app.services.admin_catalog_service import AdminCatalogService
from app.services.appointment_service import AppointmentService
from app.services.staff_access_service import StaffAccessService
from app.security.staff_context import StaffContext
from app.security.tokens import create_access_token
from tests.test_admin_ops_rbac_api import StubAudit
from tests.test_current_staff_resolution import FakeAuthRepository

BACKEND = Path(__file__).resolve().parents[1]
PROVIDER_A, PROVIDER_B = uuid4(), uuid4()
DOCTOR = uuid4()
REASON = "Licence could not be confirmed with the syndicate."


def _staff(role="provider_admin", provider_id=PROVIDER_A):
    return StaffContext(user_id=uuid4(), membership_id=uuid4(), provider_id=provider_id,
                        role=role, doctor_id=uuid4() if role == "doctor" else None)


@pytest.fixture
def enforcement(monkeypatch):
    """Set DOCTOR_VERIFICATION_ENFORCED for the duration of a test."""

    def set_to(value):
        monkeypatch.setenv("DOCTOR_VERIFICATION_ENFORCED", value)
        get_settings.cache_clear()

    yield set_to
    get_settings.cache_clear()


# ============================================================ fake admin repository


class FakeAdminRepository:
    """One doctor; a transaction that a commit keeps and a rollback undoes."""

    def __init__(self, status, provider_id=PROVIDER_A, lose_race=False, fail_flush=False):
        self.calls = []
        self.lose_race = lose_race
        self.fail_flush = fail_flush
        self.doctor = SimpleNamespace(
            id=DOCTOR, provider_id=provider_id, specialty_id=uuid4(), full_name_ar="د. اختبار",
            full_name_en="Dr Test", license_number=None, consultation_fee=None, experience_years=None,
            gender=None, accepting_new_patients=True, verification_status=status, is_active=True,
        )
        self.committed_status = status
        self.staged, self.committed = [], []
        self.audit_staged, self.audit_committed = [], []
        self.session = SimpleNamespace(commit=self._commit, rollback=self._rollback)

    def _commit(self):
        self.calls.append("commit")
        self.committed_status = self.doctor.verification_status
        self.committed += self.staged
        self.audit_committed += self.audit_staged
        self.staged, self.audit_staged = [], []

    def _rollback(self):
        self.calls.append("rollback")
        self.doctor.verification_status = self.committed_status
        self.staged, self.audit_staged = [], []

    def get_doctor(self, provider_id, doctor_id):
        self.calls.append("get_doctor")
        if (provider_id, doctor_id) == (self.doctor.provider_id, self.doctor.id):
            return self.doctor
        return None

    def set_doctor_verification_status(self, *, provider_id, doctor_id, expected_status, new_status):
        self.calls.append(("set_status", expected_status, new_status))
        if self.lose_race or self.doctor.verification_status != expected_status:
            return False
        self.doctor.verification_status = new_status
        return True

    def add(self, row):
        self.calls.append("add")
        self.staged.append(row)

    def flush(self):
        self.calls.append("flush")
        if self.fail_flush:
            raise IntegrityError("INSERT", {}, Exception("simulated constraint failure"))

    def refresh(self, row):
        self.calls.append("refresh")

    def doctor_link_ids(self, provider_id, doctor_id):
        return [], []

    def audit_hook(self, resource_id):
        self.calls.append(("audit", resource_id))
        self.audit_staged.append(resource_id)


def _service(repository):
    return AdminCatalogService(repository=repository, idempotency_service=None)


def _decide(repository, decision, reason=None, reviewer=None, provider_id=PROVIDER_A):
    return _service(repository).decide_doctor_verification(
        provider_id=provider_id, doctor_id=DOCTOR, decision=decision, reason=reason,
        reviewer=reviewer or _staff(), audit=repository.audit_hook,
    )


def _resubmit(repository, reviewer=None):
    return _service(repository).resubmit_doctor_verification(
        provider_id=PROVIDER_A, doctor_id=DOCTOR, reviewer=reviewer or _staff(), audit=repository.audit_hook,
    )


# ============================================================ transitions (service)


@pytest.mark.parametrize(
    "status, action, new_status, reason",
    [
        ("pending", "verified", "verified", None),
        ("pending", "rejected", "rejected", REASON),
        ("verified", "rejected", "rejected", REASON),
        ("rejected", "resubmitted", "pending", None),
    ],
)
def test_each_allowed_transition_writes_one_decision_and_one_audit_row_in_one_commit(
    status, action, new_status, reason,
):
    repository = FakeAdminRepository(status)
    reviewer = _staff()

    if action == "resubmitted":
        result = _resubmit(repository, reviewer)
    else:
        result = _decide(repository, action, reason, reviewer)

    assert result.verification_status == new_status
    assert repository.committed_status == new_status
    (decision,) = repository.committed
    assert isinstance(decision, DoctorVerificationDecision)
    assert (decision.decision, decision.previous_status, decision.reason) == (action, status, reason)
    assert (decision.provider_id, decision.doctor_id) == (PROVIDER_A, DOCTOR)
    assert (decision.reviewer_user_id, decision.reviewer_membership_id) == (reviewer.user_id, reviewer.membership_id)
    assert repository.audit_committed == [str(DOCTOR)]
    # The status change, the decision row and the audit row precede one commit.
    assert repository.calls.count("commit") == 1
    assert repository.calls.index(("audit", str(DOCTOR))) < repository.calls.index("commit")
    assert "rollback" not in repository.calls


def test_an_approval_never_stores_a_reason():
    repository = FakeAdminRepository("pending")

    _decide(repository, "verified", reason="ignored")

    assert repository.committed[0].reason is None


@pytest.mark.parametrize("status, action", [("verified", "verified"), ("pending", "resubmitted")])
def test_repeating_an_approval_or_resubmission_is_a_no_op(status, action):
    repository = FakeAdminRepository(status)

    result = _resubmit(repository) if action == "resubmitted" else _decide(repository, action)

    assert result.verification_status == status
    assert repository.calls == ["get_doctor"]  # no update, no record, no audit, no commit
    assert repository.committed == [] and repository.audit_committed == []


@pytest.mark.parametrize(
    "status, action",
    [("rejected", "verified"), ("rejected", "rejected"), ("verified", "resubmitted")],
)
def test_transitions_that_are_not_allowed_are_409_without_changes(status, action):
    repository = FakeAdminRepository(status)

    with pytest.raises(HTTPException) as error:
        if action == "resubmitted":
            _resubmit(repository)
        else:
            _decide(repository, action, REASON if action == "rejected" else None)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "DOCTOR_VERIFICATION_CONFLICT"
    assert repository.committed_status == status
    assert repository.committed == [] and repository.audit_committed == []
    assert not [c for c in repository.calls if isinstance(c, tuple) and c[0] == "set_status"]


def test_a_concurrent_status_change_is_409_and_records_nothing():
    repository = FakeAdminRepository("pending", lose_race=True)

    with pytest.raises(HTTPException) as error:
        _decide(repository, "verified")

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "DOCTOR_VERIFICATION_CONFLICT"
    assert repository.committed == [] and repository.audit_committed == []
    assert repository.calls[-1] == "rollback"


def test_a_failed_write_rolls_back_the_status_and_leaves_no_history():
    repository = FakeAdminRepository("pending", fail_flush=True)

    with pytest.raises(IntegrityError):
        _decide(repository, "rejected", REASON)

    assert repository.committed_status == "pending"
    assert repository.doctor.verification_status == "pending"
    assert repository.committed == [] and repository.audit_committed == []
    assert "commit" not in repository.calls and repository.calls[-1] == "rollback"


def test_another_providers_doctor_is_404_without_changes():
    repository = FakeAdminRepository("pending", provider_id=PROVIDER_B)

    with pytest.raises(HTTPException) as error:
        _decide(repository, "verified")

    assert error.value.status_code == 404
    assert error.value.detail["code"] == "DOCTOR_NOT_FOUND"
    assert repository.doctor.verification_status == "pending"
    assert repository.calls == ["get_doctor", "rollback"]


def test_rejection_touches_only_the_doctor_status_and_history():
    # Existing appointments are not cancelled: the workflow calls no
    # appointment, slot or booking operation at all.
    repository = FakeAdminRepository("verified")

    _decide(repository, "rejected", REASON)

    used = {c if isinstance(c, str) else c[0] for c in repository.calls}
    assert used <= {"get_doctor", "set_status", "add", "flush", "refresh", "audit", "commit"}
    source = inspect.getsource(admin_service_module.AdminCatalogService._change_doctor_verification)
    assert "appointment" not in source.lower() and "slot" not in source.lower()


def test_the_transition_table_is_the_documented_contract():
    assert admin_service_module.VERIFICATION_TRANSITIONS == {
        ("pending", "verified"): "verified",
        ("pending", "rejected"): "rejected",
        ("verified", "rejected"): "rejected",
        ("rejected", "resubmitted"): "pending",
    }
    assert admin_service_module.VERIFICATION_NO_OPS == {("verified", "verified"), ("pending", "resubmitted")}


# ============================================================ endpoints (HTTP)


@pytest.fixture
def verification_api():
    state = SimpleNamespace(repository=FakeAdminRepository("pending"), audit=StubAudit(), staff=_staff())
    app = FastAPI()
    app.include_router(admin_catalog.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=PROVIDER_A, tenant_key="clinic-001", timezone="Africa/Cairo",
    )
    app.dependency_overrides[deps.get_admin_catalog_service] = lambda: _service(state.repository)
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: state.audit

    def use_staff(staff):
        state.staff = staff
        if staff is None:
            app.dependency_overrides.pop(deps.get_current_staff, None)
            # Never reached: the missing bearer token is rejected first.
            app.dependency_overrides[deps.get_staff_access_service] = lambda: object()
        else:
            app.dependency_overrides[deps.get_current_staff] = lambda: state.staff

    use_staff(state.staff)
    client = TestClient(app)
    state.use_staff = use_staff
    state.verify = lambda body, doctor=DOCTOR: client.post(f"/api/v1/admin/doctors/{doctor}/verification", json=body)
    state.resubmit = lambda doctor=DOCTOR: client.post(f"/api/v1/admin/doctors/{doctor}/resubmit")
    return state


def _audit_actions(state):
    return [r["action"] for r in state.audit.records]


def test_a_provider_admin_approves_a_pending_doctor(verification_api):
    response = verification_api.verify({"decision": "verified"})

    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    assert "reason" not in response.json()
    assert _audit_actions(verification_api) == ["doctor.verify"]
    assert verification_api.audit.records[0]["resource_id"] == str(DOCTOR)
    (decision,) = verification_api.repository.committed
    assert decision.reviewer_user_id == verification_api.staff.user_id


def test_a_provider_admin_rejects_with_a_trimmed_reason(verification_api):
    response = verification_api.verify({"decision": "rejected", "reason": f"   {REASON}\n"})

    assert response.status_code == 200
    assert response.json()["verification_status"] == "rejected"
    assert verification_api.repository.committed[0].reason == REASON
    assert _audit_actions(verification_api) == ["doctor.reject"]
    # The reason lives only in the decision history, never in the audit row.
    assert REASON not in str(verification_api.audit.records)


def test_a_500_character_reason_padded_with_spaces_is_accepted(verification_api):
    reason = "r" * 500

    response = verification_api.verify({"decision": "rejected", "reason": f"  {reason}  "})

    assert response.status_code == 200
    assert verification_api.repository.committed[0].reason == reason


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "rejected"},
        {"decision": "rejected", "reason": None},
        {"decision": "rejected", "reason": ""},
        {"decision": "rejected", "reason": "   \t "},
        {"decision": "rejected", "reason": "r" * 501},
        {"decision": "verified", "reason": "not allowed on approval"},
        {"decision": "approved"},
        {"decision": "pending"},
        {"decision": "resubmitted"},
        {},
    ],
    ids=["no-reason", "null-reason", "empty-reason", "blank-reason", "too-long-reason",
         "reason-on-approval", "unknown-decision", "pending-decision", "resubmit-decision", "empty-body"],
)
def test_invalid_requests_are_422_without_changes(verification_api, body):
    response = verification_api.verify(body)

    assert response.status_code == 422
    assert verification_api.repository.calls == []
    assert verification_api.audit.records == []


@pytest.mark.parametrize("role", ["doctor", "receptionist", "lab_staff"])
def test_other_roles_are_403(verification_api, role):
    verification_api.use_staff(_staff(role))

    assert verification_api.verify({"decision": "verified"}).status_code == 403
    assert verification_api.resubmit().status_code == 403
    assert verification_api.repository.calls == [] and verification_api.audit.records == []


def test_missing_credentials_are_401(verification_api):
    verification_api.use_staff(None)

    assert verification_api.verify({"decision": "verified"}).status_code == 401
    assert verification_api.resubmit().status_code == 401
    assert verification_api.repository.calls == [] and verification_api.audit.records == []


def test_another_providers_doctor_is_a_safe_404(verification_api):
    verification_api.repository = FakeAdminRepository("pending", provider_id=PROVIDER_B)

    for response in (verification_api.verify({"decision": "verified"}), verification_api.resubmit()):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "DOCTOR_NOT_FOUND"
    assert verification_api.repository.doctor.verification_status == "pending"
    assert verification_api.audit.records == []


def test_resubmission_returns_a_rejected_doctor_to_pending(verification_api):
    verification_api.repository = FakeAdminRepository("rejected")

    response = verification_api.resubmit()

    assert response.status_code == 200
    assert response.json()["verification_status"] == "pending"
    assert verification_api.repository.committed[0].decision == "resubmitted"
    assert _audit_actions(verification_api) == ["doctor.resubmit"]


def test_endpoint_conflicts_and_no_ops(verification_api):
    verification_api.repository = FakeAdminRepository("verified")

    repeat = verification_api.verify({"decision": "verified"})
    resubmit = verification_api.resubmit()

    assert repeat.status_code == 200 and repeat.json()["verification_status"] == "verified"
    assert resubmit.status_code == 409
    assert resubmit.json()["detail"]["code"] == "DOCTOR_VERIFICATION_CONFLICT"
    assert verification_api.repository.committed == [] and verification_api.audit.records == []


def test_the_endpoints_are_staff_bearer_routes_in_the_schema():
    paths = FastAPI()
    paths.include_router(admin_catalog.router, prefix="/api/v1")
    schema = paths.openapi()["paths"]

    for path in ("/api/v1/admin/doctors/{doctor_id}/verification", "/api/v1/admin/doctors/{doctor_id}/resubmit"):
        assert schema[path]["post"]["security"] == [{"HTTPBearer": []}]


@pytest.mark.parametrize(
    "status, body",
    [("rejected", {"decision": "verified"}), ("rejected", {"decision": "rejected", "reason": REASON})],
    ids=["rejected-then-verify", "rejected-then-reject-again"],
)
def test_disallowed_transitions_are_409_over_http(verification_api, status, body):
    verification_api.repository = FakeAdminRepository(status)

    response = verification_api.verify(body)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DOCTOR_VERIFICATION_CONFLICT"
    assert verification_api.repository.committed_status == status
    assert verification_api.repository.committed == [] and verification_api.audit.records == []


def test_resubmitting_a_pending_doctor_is_a_200_no_op_over_http(verification_api):
    response = verification_api.resubmit()

    assert response.status_code == 200
    assert response.json()["verification_status"] == "pending"
    assert verification_api.repository.calls == ["get_doctor"]  # no update, record, audit or commit
    assert verification_api.repository.committed == [] and verification_api.audit.records == []


def test_a_concurrent_status_change_is_409_over_http(verification_api):
    verification_api.repository = FakeAdminRepository("pending", lose_race=True)

    response = verification_api.verify({"decision": "verified"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DOCTOR_VERIFICATION_CONFLICT"
    assert verification_api.repository.calls[-1] == "rollback"
    assert verification_api.repository.committed == [] and verification_api.audit.records == []


@pytest.mark.parametrize("route", ["verification", "resubmit"])
def test_an_invalid_doctor_id_is_422_before_any_work(verification_api, route):
    if route == "verification":
        response = verification_api.verify({"decision": "verified"}, doctor="not-a-uuid")
    else:
        response = verification_api.resubmit(doctor="not-a-uuid")

    assert response.status_code == 422
    assert verification_api.repository.calls == [] and verification_api.audit.records == []


ADMIN_DOCTOR_OUT_FIELDS = {
    "id", "provider_id", "specialty_id", "full_name_ar", "full_name_en", "license_number",
    "consultation_fee", "experience_years", "gender", "accepting_new_patients",
    "verification_status", "is_active", "branch_ids", "service_ids",
}


def test_the_response_is_the_full_admin_doctor_contract_without_the_reason(verification_api):
    branch_ids, service_ids = [uuid4(), uuid4()], [uuid4()]
    verification_api.repository.doctor_link_ids = lambda provider_id, doctor_id: (branch_ids, service_ids)
    doctor = verification_api.repository.doctor

    response = verification_api.verify({"decision": "rejected", "reason": REASON})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == ADMIN_DOCTOR_OUT_FIELDS
    assert (UUID(body["id"]), UUID(body["provider_id"]), UUID(body["specialty_id"])) == (
        doctor.id, doctor.provider_id, doctor.specialty_id,
    )
    assert (body["full_name_ar"], body["full_name_en"]) == (doctor.full_name_ar, doctor.full_name_en)
    assert body["license_number"] is None and body["consultation_fee"] is None
    assert body["experience_years"] is None and body["gender"] is None
    assert body["accepting_new_patients"] is True and body["is_active"] is True
    assert body["verification_status"] == "rejected"
    assert [UUID(i) for i in body["branch_ids"]] == branch_ids
    assert [UUID(i) for i in body["service_ids"]] == service_ids
    # The rejection reason is kept in the decision history only.
    assert REASON not in response.text


# ============================================================ endpoints: real auth and tenant (HTTP)
# The real get_current_provider, get_current_staff and require_staff_roles:
# real JWT decoding and staff resolution over in-memory fakes.


TEST_JWT_SECRET = "test-only-signing-key-not-production-0123456789abcdef"
TENANT_A = "clinic-001"


class FakeProviderCatalog:
    """The only CatalogService call get_current_provider makes."""

    def __init__(self):
        self.lookups = []

    def get_provider(self, tenant_key):
        self.lookups.append(tenant_key)
        if tenant_key == TENANT_A:
            return SimpleNamespace(id=PROVIDER_A, tenant_key=TENANT_A, timezone="Africa/Cairo")
        return None


def _no_database_session():
    raise AssertionError("a database session was requested")


@pytest.fixture
def real_auth_api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    get_settings.cache_clear()
    state = SimpleNamespace(
        repository=FakeAdminRepository("pending"), audit=StubAudit(),
        catalog=FakeProviderCatalog(), auth=FakeAuthRepository(),
    )
    app = FastAPI()
    app.include_router(admin_catalog.router, prefix="/api/v1")
    # Only the database-backed dependencies are replaced; any other request
    # for a session fails the test instead of connecting.
    app.dependency_overrides[deps.get_db_session] = _no_database_session
    app.dependency_overrides[deps.get_catalog_service] = lambda: state.catalog
    app.dependency_overrides[deps.get_staff_access_service] = lambda: StaffAccessService(state.auth)
    app.dependency_overrides[deps.get_admin_catalog_service] = lambda: _service(state.repository)
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: state.audit
    client = TestClient(app)

    def sign_in(role="provider_admin", token_provider=PROVIDER_A, missing=None):
        """A staff member of provider A; returns a real access token."""
        state.user = SimpleNamespace(id=uuid4())
        state.membership = SimpleNamespace(
            id=uuid4(), user_id=state.user.id, provider_id=PROVIDER_A, role=role,
            doctor_id=uuid4() if role == "doctor" else None,
        )
        state.auth = FakeAuthRepository(
            user=None if missing == "user" else state.user,
            membership=None if missing == "membership" else state.membership,
        )
        return create_access_token(
            user_id=state.user.id, membership_id=state.membership.id, provider_id=token_provider,
        )

    def post(route, token, tenant, body=None):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if tenant is not None:
            headers["X-Tenant-ID"] = tenant
        return client.post(f"/api/v1/admin/doctors/{DOCTOR}/{route}", json=body, headers=headers)

    state.sign_in = sign_in
    state.call = lambda route, token, tenant=TENANT_A: post(
        route, token, tenant, {"decision": "verified"} if route == "verification" else None,
    )
    yield state
    get_settings.cache_clear()


def _untouched(api):
    return api.repository.calls == [] and api.audit.records == []


def test_a_real_provider_admin_token_verifies_a_doctor(real_auth_api):
    token = real_auth_api.sign_in()

    response = real_auth_api.call("verification", token)

    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    assert real_auth_api.catalog.lookups == [TENANT_A]
    assert real_auth_api.auth.membership_calls == [{
        "membership_id": real_auth_api.membership.id, "user_id": real_auth_api.user.id,
        "provider_id": PROVIDER_A,
    }]
    (decision,) = real_auth_api.repository.committed
    assert (decision.reviewer_user_id, decision.reviewer_membership_id) == (
        real_auth_api.user.id, real_auth_api.membership.id,
    )
    (record,) = real_auth_api.audit.records
    assert (record["action"], record["user_id"]) == ("doctor.verify", real_auth_api.user.id)


def test_a_real_provider_admin_token_resubmits_a_rejected_doctor(real_auth_api):
    real_auth_api.repository = FakeAdminRepository("rejected")
    token = real_auth_api.sign_in()

    response = real_auth_api.call("resubmit", token)

    assert response.status_code == 200
    assert response.json()["verification_status"] == "pending"
    assert [r["action"] for r in real_auth_api.audit.records] == ["doctor.resubmit"]


@pytest.mark.parametrize("route", ["verification", "resubmit"])
def test_a_token_for_another_provider_is_403_staff_tenant_mismatch(real_auth_api, route):
    token = real_auth_api.sign_in(token_provider=PROVIDER_B)

    response = real_auth_api.call(route, token)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "STAFF_TENANT_MISMATCH"
    # Refused before any user or membership lookup.
    assert real_auth_api.auth.user_calls == [] and real_auth_api.auth.membership_calls == []
    assert _untouched(real_auth_api)


@pytest.mark.parametrize("missing", ["membership", "user"])
@pytest.mark.parametrize("route", ["verification", "resubmit"])
def test_an_inactive_or_missing_staff_session_is_401(real_auth_api, route, missing):
    token = real_auth_api.sign_in(missing=missing)

    response = real_auth_api.call(route, token)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_STAFF_SESSION"
    assert _untouched(real_auth_api)


@pytest.mark.parametrize("token_kind", ["not-a-jwt", "other-signing-key"])
@pytest.mark.parametrize("route", ["verification", "resubmit"])
def test_an_invalid_access_token_is_401(real_auth_api, route, token_kind):
    real_auth_api.sign_in()
    if token_kind == "not-a-jwt":
        token = "not-a-jwt"
    else:
        token = create_access_token(
            user_id=real_auth_api.user.id, membership_id=real_auth_api.membership.id,
            provider_id=PROVIDER_A,
            settings=Settings(_env_file=None, jwt_secret_key="another-test-only-key-0123456789abcdefghijkl"),
        )

    response = real_auth_api.call(route, token)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_ACCESS_TOKEN"
    assert real_auth_api.auth.user_calls == [] and _untouched(real_auth_api)


@pytest.mark.parametrize("role", ["doctor", "receptionist", "lab_staff"])
@pytest.mark.parametrize("route", ["verification", "resubmit"])
def test_a_resolved_non_admin_staff_member_is_403(real_auth_api, route, role):
    token = real_auth_api.sign_in(role=role)

    response = real_auth_api.call(route, token)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "STAFF_PERMISSION_DENIED"
    assert len(real_auth_api.auth.membership_calls) == 1  # the session itself was valid
    assert _untouched(real_auth_api)


@pytest.mark.parametrize("route", ["verification", "resubmit"])
def test_a_missing_tenant_header_is_422(real_auth_api, route):
    token = real_auth_api.sign_in()

    response = real_auth_api.call(route, token, tenant=None)

    assert response.status_code == 422
    assert real_auth_api.catalog.lookups == []
    assert _untouched(real_auth_api)


@pytest.mark.parametrize("route", ["verification", "resubmit"])
def test_an_unknown_tenant_is_404_provider_not_found(real_auth_api, route):
    token = real_auth_api.sign_in()

    response = real_auth_api.call(route, token, tenant="unknown-tenant")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PROVIDER_NOT_FOUND"
    assert real_auth_api.catalog.lookups == ["unknown-tenant"]
    # The provider is resolved before the staff session.
    assert real_auth_api.auth.user_calls == [] and _untouched(real_auth_api)


# ============================================================ catalog and search eligibility


class CapturingSession:
    def __init__(self):
        self.statements = []

    def scalars(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: [])

    def scalar(self, statement):
        self.statements.append(statement)
        return None

    def execute(self, statement, params=None):
        self.statements.append(statement)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))


def _compiled(statement):
    compiled = statement.compile()
    return str(compiled).replace("\n", " "), compiled.params


def _bound(sql, params, column):
    """The value bound to `column = :param` (bind names vary per query)."""
    match = re.search(rf"{re.escape(column)} = :(\w+)", sql)
    assert match, column
    return params[match.group(1)]


def _catalog_and_search_statements():
    session = CapturingSession()
    catalog = CatalogRepository(session)
    search = SearchRepository(session)
    catalog.list_doctors(provider_id=PROVIDER_A, specialty_id=None, branch_id=None, service_id=None)
    catalog.doctor_is_active(provider_id=PROVIDER_A, doctor_id=DOCTOR)
    catalog.list_available_slots(provider_id=PROVIDER_A, slot_date=date(2026, 10, 20), doctor_id=None,
                                 branch_id=None, limit=10)
    search.search_doctors(provider_id=None, org_type=None, branch_id=None, governorate=None,
                          specialty_code=None, service_code=None, name=None, limit=10)
    search.search_availability(date_from=date(2026, 10, 20), date_to=date(2026, 10, 20), time_from=None,
                               time_to=None, provider_id=None, org_type=None, branch_id=None,
                               governorate=None, doctor_id=None, specialty_code=None, limit=10)
    names = ["list_doctors", "doctor_is_active", "list_available_slots", "search_doctors", "search_availability"]
    return dict(zip(names, session.statements))


def test_the_default_keeps_active_only_doctor_eligibility(enforcement):
    enforcement("false")

    for name, statement in _catalog_and_search_statements().items():
        sql, _ = _compiled(statement)
        assert "doctors.is_active =" in sql, name
        # The column may be selected (GET /doctors returns it) but never filtered.
        assert "doctors.verification_status =" not in sql, name


def test_enforced_eligibility_requires_verified_doctors_everywhere(enforcement):
    enforcement("true")

    for name, statement in _catalog_and_search_statements().items():
        sql, params = _compiled(statement)
        assert "doctors.is_active" in sql, name
        assert _bound(sql, params, "doctors.verification_status") == "verified", name


def test_enforced_slots_keep_doctorless_lab_slots(enforcement):
    enforcement("true")

    sql, params = _compiled(_catalog_and_search_statements()["list_available_slots"])

    assert "doctor_availability_slots.doctor_id IS NULL" in sql
    assert _bound(sql, params, "providers.org_type") == "diagnostic_lab"  # lab branch, unchanged
    # Verification only applies inside the doctor branch of the OR.
    lab_branch, doctor_branch = sql.split("doctor_availability_slots.doctor_id IS NULL", 1)[1].split(" OR ", 1)
    assert "verification_status" not in lab_branch and "verification_status" in doctor_branch


def test_provider_scoping_is_unchanged_when_enforced(enforcement):
    enforcement("true")
    statements = _catalog_and_search_statements()

    for name in ("list_doctors", "doctor_is_active", "list_available_slots"):
        sql, params = _compiled(statements[name])
        assert _bound(sql, params, "doctors.provider_id") == PROVIDER_A, name


SPECIALTY = uuid4()


def _services_sql(**filters):
    session = CapturingSession()
    CatalogRepository(session).list_services(provider_id=PROVIDER_A, **filters)
    (statement,) = session.statements
    return _compiled(statement)


def test_services_by_specialty_keep_active_only_eligibility_by_default(enforcement):
    enforcement("false")

    sql, params = _services_sql(specialty_id=SPECIALTY)

    assert sql.startswith("SELECT DISTINCT")
    assert _bound(sql, params, "doctors.specialty_id") == SPECIALTY
    assert _bound(sql, params, "doctors.provider_id") == PROVIDER_A
    assert _bound(sql, params, "doctors.is_active") == 1
    assert "verification_status" not in sql


def test_enforced_services_by_specialty_require_a_verified_doctor(enforcement):
    enforcement("true")

    sql, params = _services_sql(specialty_id=SPECIALTY)

    # DISTINCT over the doctor join: one eligible doctor keeps the service.
    assert sql.startswith("SELECT DISTINCT")
    assert _bound(sql, params, "doctors.specialty_id") == SPECIALTY
    assert _bound(sql, params, "doctors.provider_id") == PROVIDER_A
    assert _bound(sql, params, "doctors.is_active") == 1
    assert _bound(sql, params, "doctors.verification_status") == "verified"


@pytest.mark.parametrize("value", ["false", "true"])
@pytest.mark.parametrize(
    "filters",
    [{}, {"service_type": "diagnostic"}, {"doctor_id": DOCTOR}],
    ids=["no-filter", "lab-service-type", "doctor-id"],
)
def test_services_without_a_specialty_never_join_doctors(enforcement, value, filters):
    enforcement(value)

    sql, params = _services_sql(**filters)

    assert not re.search(r"\bdoctors\b", sql)
    assert "verification_status" not in sql
    if "doctor_id" in filters:
        # Unchanged: only the doctor-service link is checked, not the doctor.
        assert _bound(sql, params, "doctor_services.doctor_id") == DOCTOR
    else:
        assert "doctor_services" not in sql


def test_working_hours_and_slot_generation_ignore_verification():
    for relative in ("app/services/working_hours_service.py", "app/api/routers/admin_working_hours.py"):
        assert "verification" not in (BACKEND / relative).read_text(encoding="utf-8"), relative


# ============================================================ booking and rescheduling


class BookingRepository:
    """Records every call; any write fails the test."""

    def __init__(self, verified, doctor_id=DOCTOR):
        self.verified = verified
        self.calls = []
        self.session = SimpleNamespace(commit=lambda: self.calls.append("commit"),
                                       rollback=lambda: self.calls.append("rollback"))
        tomorrow = date.today() + timedelta(days=2)
        self.slot = {"id": uuid4(), "provider_id": PROVIDER_A, "doctor_id": doctor_id, "branch_id": uuid4(),
                     "slot_date": tomorrow, "start_time": time(10), "end_time": time(10, 30), "status": "available"}

    def lock_slot(self, *, provider_id, slot_id):
        self.calls.append("lock_slot")
        return dict(self.slot)

    def doctor_branch_is_valid(self, *, provider_id, doctor_id, branch_id):
        self.calls.append("doctor_branch_is_valid")
        return True

    def doctor_is_verified(self, *, provider_id, doctor_id):
        self.calls.append(("doctor_is_verified", provider_id, doctor_id))
        return self.verified

    def lock_appointment_by_reference(self, *, provider_id, appointment_reference):
        self.calls.append("lock_appointment")
        return {"id": uuid4(), "provider_id": PROVIDER_A, "patient_id": PATIENT, "slot_id": uuid4(),
                "service_id": uuid4(), "status": "confirmed", "appointment_reference": "APT-1"}

    def __getattr__(self, name):
        def write(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"unexpected repository call after the eligibility check: {name}")
        return write


PATIENT = uuid4()


class StopAfterEligibility(Exception):
    """Raised by the branch-profile step that follows the eligibility check."""


def _booking_service(repository):
    service = AppointmentService.__new__(AppointmentService)
    service.repository = repository
    service.idempotency_service = None
    service.branch_profile_service = SimpleNamespace(
        resolve=lambda **_: (_ for _ in ()).throw(StopAfterEligibility()),
    )
    service._resolve_patient_by_national_id = lambda **_: SimpleNamespace(id=PATIENT)
    return service


def _create(service):
    return service.create_confirmed_booking(
        provider_id=PROVIDER_A, provider_timezone="Africa/Cairo",
        data=AppointmentCreateRequest(national_id="00000000000000", slot_id=uuid4(), service_id=uuid4(),
                                      channel="voice"),
    )


def test_enforced_booking_of_an_unverified_doctor_is_409_before_any_write(enforcement):
    enforcement("true")
    repository = BookingRepository(verified=False)

    with pytest.raises(HTTPException) as error:
        _create(_booking_service(repository))

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "DOCTOR_NOT_BOOKABLE"
    assert repository.calls == ["lock_slot", "doctor_branch_is_valid",
                                ("doctor_is_verified", PROVIDER_A, DOCTOR), "rollback"]


def test_enforced_booking_of_a_verified_doctor_passes_the_check(enforcement):
    enforcement("true")
    repository = BookingRepository(verified=True)

    with pytest.raises(StopAfterEligibility):
        _create(_booking_service(repository))

    assert ("doctor_is_verified", PROVIDER_A, DOCTOR) in repository.calls


def test_the_default_does_not_check_verification_when_booking(enforcement):
    enforcement("false")
    repository = BookingRepository(verified=False)

    with pytest.raises(StopAfterEligibility):
        _create(_booking_service(repository))

    assert not [c for c in repository.calls if isinstance(c, tuple)]


def test_enforced_lab_slots_without_a_doctor_are_not_checked(enforcement, monkeypatch):
    enforcement("true")
    repository = BookingRepository(verified=False, doctor_id=None)
    service = _booking_service(repository)
    monkeypatch.setattr(service, "_ensure_lab_slot_service", lambda **_: None)

    with pytest.raises(StopAfterEligibility):
        _create(service)

    assert not [c for c in repository.calls if isinstance(c, tuple)]


def test_enforced_rescheduling_onto_an_unverified_doctor_is_409_before_any_write(enforcement):
    enforcement("true")
    repository = BookingRepository(verified=False)
    service = _booking_service(repository)

    with pytest.raises(HTTPException) as error:
        service.reschedule_booking(
            provider_id=PROVIDER_A, provider_timezone="Africa/Cairo", appointment_reference="APT-1",
            data=SimpleNamespace(national_id="00000000000000", new_slot_id=uuid4(), reason=None,
                                 changed_by="ai_agent", actor_reference=None,
                                 model_dump=lambda **_: {}),
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "DOCTOR_NOT_BOOKABLE"
    assert repository.calls[-1] == "rollback"
    for write in ("release_slot", "mark_slot_booked", "update_appointment_for_reschedule",
                  "insert_reschedule_history", "commit"):
        assert write not in repository.calls


def test_the_eligibility_check_runs_before_every_booking_write():
    create = inspect.getsource(AppointmentService.create_confirmed_booking)
    reschedule = inspect.getsource(AppointmentService.reschedule_booking)

    assert create.index("_ensure_doctor_bookable(") < create.index("branch_profile_service")
    assert create.index("_ensure_doctor_bookable(") < create.index("insert_appointment(")
    assert reschedule.index("_ensure_doctor_bookable(") < reschedule.index("release_slot(")
    assert reschedule.index("_ensure_doctor_bookable(") < reschedule.index("mark_slot_booked(")


def test_the_booking_verification_sql_is_tenant_scoped():
    from app.repositories.appointment_repository import AppointmentRepository

    sql = inspect.getsource(AppointmentRepository.doctor_is_verified)
    assert "doctor.provider_id = :provider_id" in sql
    assert "doctor.verification_status = 'verified'" in sql


def test_the_booking_verification_read_holds_a_shared_row_lock():
    # Offline: proves the SQL sent, not the locking itself (that needs the
    # opt-in database concurrency tests).
    from app.repositories.appointment_repository import AppointmentRepository

    executed = []

    class Session:
        def execute(self, statement, params):
            executed.append((statement, params))
            return SimpleNamespace(first=lambda: None)

    assert AppointmentRepository(Session()).doctor_is_verified(provider_id=PROVIDER_A, doctor_id=DOCTOR) is False

    (statement, params), = executed
    sql = " ".join(str(statement).split())
    assert "FROM dbo.doctors AS doctor WITH ( HOLDLOCK, ROWLOCK ) WHERE" in sql
    assert "UPDLOCK" not in sql
    assert params == {"provider_id": str(PROVIDER_A), "doctor_id": str(DOCTOR)}


def test_the_slot_lock_comes_before_the_eligibility_check():
    create = inspect.getsource(AppointmentService.create_confirmed_booking)
    reschedule = inspect.getsource(AppointmentService.reschedule_booking)

    assert create.index("lock_slot(") < create.index("_ensure_doctor_bookable(")
    assert reschedule.index("lock_appointment_by_reference(") < reschedule.index("lock_slot(")
    assert reschedule.index("lock_slot(") < reschedule.index("_ensure_doctor_bookable(")


def test_enforced_rescheduling_locks_before_the_check_and_writes_nothing(enforcement):
    enforcement("true")
    repository = BookingRepository(verified=False)

    with pytest.raises(HTTPException):
        _booking_service(repository).reschedule_booking(
            provider_id=PROVIDER_A, provider_timezone="Africa/Cairo", appointment_reference="APT-1",
            data=SimpleNamespace(national_id="00000000000000", new_slot_id=uuid4(), reason=None,
                                 changed_by="ai_agent", actor_reference=None,
                                 model_dump=lambda **_: {}),
        )

    check = ("doctor_is_verified", PROVIDER_A, DOCTOR)
    calls = repository.calls
    assert calls.index("lock_appointment") < calls.index("lock_slot") < calls.index(check)
    assert calls[calls.index(check) + 1:] == ["rollback"]


# ============================================================ rollout setting


def test_enforcement_is_off_by_default(monkeypatch):
    monkeypatch.delenv("DOCTOR_VERIFICATION_ENFORCED", raising=False)

    assert Settings(_env_file=None).doctor_verification_enforced is False


@pytest.mark.parametrize("raw, expected", [("true", True), ("false", False), (" TRUE ", True)])
def test_enforcement_accepts_only_true_or_false(monkeypatch, raw, expected):
    monkeypatch.setenv("DOCTOR_VERIFICATION_ENFORCED", raw)

    assert Settings(_env_file=None).doctor_verification_enforced is expected


@pytest.mark.parametrize("raw", ["1", "yes", "on", ""])
def test_enforcement_rejects_ambiguous_values(monkeypatch, raw):
    monkeypatch.setenv("DOCTOR_VERIFICATION_ENFORCED", raw)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


# ============================================================ migration (not applied)

MIGRATION = BACKEND / "migrations" / "versions" / "c3d9e6a2f8b1_add_doctor_verification_decisions.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("doctor_verification_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOp:
    def __init__(self):
        self.operations = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.operations.append((name, args, kwargs))


def test_the_migration_is_the_single_new_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    module = _load_migration()

    assert script.get_heads() == ["c3d9e6a2f8b1"]
    assert (module.revision, module.down_revision) == ("c3d9e6a2f8b1", "a8c2e5f1b7d4")


MEMBERSHIP_KEY = "uq_provider_memberships_id_user_provider"


def _migration_operations(monkeypatch, step):
    module = _load_migration()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)
    getattr(module, step)()
    return recorder.operations


def test_the_migration_adds_one_key_and_one_table_and_reverses_them_in_order(monkeypatch):
    upgrade = _migration_operations(monkeypatch, "upgrade")
    downgrade = _migration_operations(monkeypatch, "downgrade")

    assert [name for name, _, _ in upgrade] == ["create_unique_constraint", "create_table", "create_index"]
    # The key exists before the table whose foreign key references it.
    assert upgrade[0][1] == (MEMBERSHIP_KEY, "provider_memberships", ["id", "user_id", "provider_id"])
    assert upgrade[1][1][0] == "doctor_verification_decisions"
    # Reverse order: the table (and its foreign keys) before the key it references.
    assert [name for name, _, _ in downgrade] == ["drop_index", "drop_table", "drop_constraint"]
    assert downgrade[1][1] == ("doctor_verification_decisions",)
    assert downgrade[2][1] == (MEMBERSHIP_KEY, "provider_memberships")
    assert downgrade[2][2] == {"type_": "unique"}


def test_the_migration_matches_the_model_constraints(monkeypatch):
    upgrade = _migration_operations(monkeypatch, "upgrade")
    _, args, _ = upgrade[1]

    migration_columns = {item.name for item in args[1:] if hasattr(item, "type")}
    migration_constraints = {item.name for item in args[1:] if not hasattr(item, "type")}
    table = DoctorVerificationDecision.__table__
    model_constraints = {c.name for c in table.constraints} | {fk.name for fk in table.foreign_keys}

    assert migration_columns == set(table.columns.keys())
    # Models leave the primary key unnamed (project convention); migrations name it.
    assert "PK_doctor_verification_decisions" in migration_constraints
    assert migration_constraints - {"PK_doctor_verification_decisions"} == {n for n in model_constraints if n}
    assert upgrade[2][1][0] == "IX_doctor_verification_decisions_provider_doctor_decided"


def test_one_composite_foreign_key_ties_the_reviewer_membership_user_and_provider():
    table = DoctorVerificationDecision.__table__
    fks = {(tuple(fk.column_keys), tuple(e.target_fullname for e in fk.elements))
           for fk in table.foreign_key_constraints}

    assert fks == {
        (("provider_id",), ("providers.id",)),
        (("doctor_id", "provider_id"), ("doctors.id", "doctors.provider_id")),
        (("reviewer_membership_id", "reviewer_user_id", "provider_id"),
         ("provider_memberships.id", "provider_memberships.user_id", "provider_memberships.provider_id")),
    }


def test_the_membership_key_is_declared_on_the_model_too():
    from app.models import ProviderMembership

    keys = {c.name: [col.name for col in c.columns]
            for c in ProviderMembership.__table__.constraints if c.name and c.name.startswith("uq_")}

    assert keys[MEMBERSHIP_KEY] == ["id", "user_id", "provider_id"]
    assert keys["uq_provider_memberships_user_provider"] == ["user_id", "provider_id"]  # unchanged


def test_the_decision_history_holds_no_sensitive_doctor_fields():
    columns = set(DoctorVerificationDecision.__table__.columns.keys())

    assert columns == {"id", "provider_id", "doctor_id", "decision", "previous_status", "reason",
                       "reviewer_user_id", "reviewer_membership_id", "decided_at"}


# ============================================================ read-only status report

REPORT = BACKEND.parent / "Database_latest" / "08_doctor_verification_status_report.sql"


def _report_statements():
    text = REPORT.read_text(encoding="utf-8")
    without_comments = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", " ", without_comments), text


def test_the_report_refuses_every_database_but_the_audit_copy():
    statements, _ = _report_statements()

    first_batch = statements.split("GO", 1)[0]
    assert "IF DB_NAME() <> N'MedMind_Audit_Final2'" in first_batch
    assert "SET NOEXEC ON" in first_batch
    assert "MedMind_Booking_DB" not in statements


def test_the_report_only_reads():
    statements, _ = _report_statements()

    for keyword in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "ALTER", "DROP", "CREATE",
                    "EXEC", "GRANT", "DENY", "REVOKE", "INTO"):
        assert not re.search(rf"\b{keyword}\b", statements, re.I), keyword


def test_the_report_selects_counts_without_personal_data():
    statements, _ = _report_statements()

    for column in ("full_name", "license", "phone", "email", "national", "bio", "photo", "patient"):
        assert column not in statements.lower(), column
    assert "COUNT(*) AS doctor_count" in statements


def _batches(statements):
    return [batch for batch in re.split(r"^\s*GO\s*$", statements, flags=re.M) if batch.strip()]


def test_the_report_stops_on_missing_objects_before_any_data_query():
    batches = _batches(_report_statements()[0])

    guard = batches[1]
    for table, column in [("doctors", "provider_id"), ("doctors", "verification_status"), ("doctors", "is_active"),
                          ("providers", "tenant_key"), ("doctor_availability_slots", "doctor_id"),
                          ("doctor_availability_slots", "slot_date"), ("doctor_availability_slots", "status"),
                          ("appointments", "doctor_id"), ("appointments", "scheduled_date"),
                          ("appointments", "status")]:
        assert f"COL_LENGTH(N'dbo.{table}', N'{column}') IS NULL" in guard, (table, column)
    assert "RAISERROR" in guard and "SET NOEXEC ON" in guard
    # No data query in the two guard batches; every query comes after them.
    assert not re.search(r"\bFROM\s+dbo\.", batches[0] + batches[1])
    # The session option is reset only in the last batch, after every query.
    assert batches[-1].strip() == "SET NOEXEC OFF;"
    assert "SET NOEXEC OFF" not in "".join(batches[:-1])


def test_the_report_covers_the_rollout_questions():
    statements, text = _report_statements()

    assert "FROM dbo.alembic_version" in statements
    assert "OBJECT_ID(N'dbo.alembic_version', N'U') IS NOT NULL" in statements
    assert "sys.indexes" in statements and "key_columns" in statements
    assert "uq_provider_memberships_id_user_provider" in statements
    assert "active_would_be_hidden" in statements
    assert "future_available_slots" in statements and "s.status = N'available'" in statements
    assert "future_active_appointments" in statements and "a.status IN (N'pending', N'confirmed')" in statements
    # Tenant-consistent joins between slots/appointments and their doctors.
    assert "d.id = s.doctor_id AND d.provider_id = s.provider_id" in statements
    assert "d.id = a.doctor_id AND d.provider_id = a.provider_id" in statements
    # The doctors key must be enabled and exactly (id, provider_id) in key order.
    assert "i.is_disabled = 0" in statements
    assert "ic.key_ordinal = 1 AND c.name = N'id'" in statements
    assert "ic.key_ordinal = 2 AND c.name = N'provider_id'" in statements
    # The new constraint name must be free for any object type and as an index name.
    assert "OBJECT_ID(N'dbo.uq_provider_memberships_id_user_provider') IS NULL" in statements
    assert "OBJECT_ID(N'dbo.uq_provider_memberships_id_user_provider', N'UQ')" not in statements
    assert "i.name = N'uq_provider_memberships_id_user_provider'" in statements
    # The verification check is found by its definition, not only by name.
    assert "cc.definition LIKE N'%verification_status%'" in statements
    assert "cc.name = N'CK_doctors_verification_status'" not in statements
    # Operator instructions: whole script only, -b, explicit -d, DB_NAME() check.
    assert "NEVER A PARTIAL SELECTION" in text
    assert "-b -d MedMind_Audit_Final2" in text and "SELECT DB_NAME();" in text


# ============================================================ rejection reason length (UTF-16)

EMOJI = "\U0001F600"  # outside the Basic Multilingual Plane: 2 UTF-16 code units


@pytest.mark.parametrize(
    "reason",
    ["a" * 500, EMOJI * 250, "a" * 498 + EMOJI, "م" * 500, f"  {EMOJI * 250}  ", "\U00020000" * 250],
    ids=["500-bmp", "250-emoji", "498-plus-emoji", "500-arabic", "padded-250-emoji", "250-cjk-ext-b"],
)
def test_reasons_up_to_500_utf16_units_are_accepted(reason):
    request = DoctorVerificationRequest(decision="rejected", reason=reason)

    assert request.reason == reason.strip()
    assert len(request.reason.encode("utf-16-le")) // 2 <= 500


@pytest.mark.parametrize(
    "reason",
    [EMOJI * 251, "a" * 499 + EMOJI, "a" * 501, "\U00020000" * 251],
    ids=["251-emoji", "499-plus-emoji", "501-bmp", "251-cjk-ext-b"],
)
def test_reasons_over_500_utf16_units_are_rejected(reason):
    # 251 emoji are only 251 Python characters but 502 NVARCHAR units.
    with pytest.raises(ValidationError):
        DoctorVerificationRequest(decision="rejected", reason=reason)


def test_an_emoji_reason_over_the_limit_is_422_over_http(verification_api):
    response = verification_api.verify({"decision": "rejected", "reason": EMOJI * 251})

    assert response.status_code == 422
    assert verification_api.repository.calls == []


def test_a_blank_reason_is_still_required_for_rejection():
    for reason in (None, "", "   ", "\n\t"):
        with pytest.raises(ValidationError):
            DoctorVerificationRequest(decision="rejected", reason=reason)


# ============================================================ migration target guard

ENV_PY = BACKEND / "migrations" / "env.py"


class FakeAlembicContext:
    def __init__(self, offline):
        self.offline = offline
        self.configured = []
        self.config = SimpleNamespace(config_file_name=None)

    def is_offline_mode(self):
        return self.offline

    def configure(self, **kwargs):
        self.configured.append(kwargs)

    def begin_transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def run_migrations(self):
        pass


def _run_env_py(monkeypatch, tmp_path, *, offline, environ):
    import runpy

    import alembic
    import sqlalchemy

    for key in ("APP_ENV", "DB_NAME", "DB_SERVER", "DB_TRUSTED_CONNECTION"):
        monkeypatch.delenv(key, raising=False)
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)  # an empty directory: no .env can be read
    get_settings.cache_clear()
    fake = FakeAlembicContext(offline)
    monkeypatch.setattr(alembic, "context", fake, raising=False)

    def no_connection(*args, **kwargs):
        raise AssertionError("a database connection was attempted")

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", no_connection)
    try:
        runpy.run_path(str(ENV_PY), run_name="alembic_env_under_test")
    finally:
        get_settings.cache_clear()
    return fake


STAGING_AUDIT = {"APP_ENV": "staging", "DB_SERVER": "localhost\\SQLEXPRESS",
                 "DB_NAME": "MedMind_Audit_Final2", "DB_TRUSTED_CONNECTION": "true"}


@pytest.mark.parametrize("offline", [True, False], ids=["offline", "online"])
@pytest.mark.parametrize(
    "environ",
    [
        {},  # no APP_ENV: the code default MedMind_Booking_DB must never be migrated
        {"APP_ENV": "development", "DB_NAME": "MedMind_Audit_Final2"},
        {"APP_ENV": "staging"},  # no explicit DB_NAME
        {**STAGING_AUDIT, "DB_NAME": "MedMind_Booking_DB"},
        {**STAGING_AUDIT, "DB_NAME": "medmind_booking_db "},
        {**STAGING_AUDIT, "DB_NAME": ""},
    ],
    ids=["no-app-env", "development", "staging-without-db-name", "booking-db", "booking-db-case", "empty-db-name"],
)
def test_alembic_refuses_an_unsafe_target_before_any_migration_step(monkeypatch, tmp_path, offline, environ):
    from app.core.db_target import UnsafeDatabaseTargetError

    with pytest.raises(UnsafeDatabaseTargetError):
        _run_env_py(monkeypatch, tmp_path, offline=offline, environ=environ)


def test_alembic_accepts_the_explicit_staging_audit_target_offline(monkeypatch, tmp_path):
    fake = _run_env_py(monkeypatch, tmp_path, offline=True, environ=STAGING_AUDIT)

    from urllib.parse import unquote_plus

    (configured,) = fake.configured
    url = unquote_plus(configured["url"])  # odbc_connect is percent-encoded
    assert "DATABASE=MedMind_Audit_Final2;" in url
    assert "MedMind_Booking_DB" not in url


def test_a_dotenv_file_cannot_select_staging_for_migrations(tmp_path, monkeypatch):
    from app.core.db_target import UnsafeDatabaseTargetError, ensure_safe_migration_target

    (tmp_path / ".env").write_text("APP_ENV=staging\nDB_NAME=MedMind_Audit_Final2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(UnsafeDatabaseTargetError):
        ensure_safe_migration_target(Settings(_env_file=str(tmp_path / ".env")), environ={})


def test_the_guard_runs_before_alembic_configures_or_connects():
    source = ENV_PY.read_text(encoding="utf-8")

    guard = source.index("ensure_safe_migration_target(settings)")
    assert guard < source.index("context.configure(")
    assert guard < source.index("from app.db.session import engine")
    assert "from app.db.session import engine" not in source.split("def run_migrations_online")[0]
