"""Security hardening without a database:

- admin catalog writes: audit row staged in the same commit, rollback on
  failure, optional idempotency (replay / conflict);
- staff login: failed-attempt throttle and equal work for unknown emails;
- /ai/debug/router: hidden outside development, service token required,
  bounded input.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import app.security.passwords as passwords
from app.api import dependencies as deps
from app.api.routers import auth, medmind_ai
from app.core.config import get_settings
from app.core.idempotency_exceptions import IdempotencyConflictError
from app.schemas.admin_catalog import AdminDoctorCreate
from app.security import login_throttle as login_throttle_module
from app.security.login_throttle import LoginThrottle
from app.security.service_auth import SERVICE_TOKEN_HEADER
from app.services.admin_catalog_service import AdminCatalogService
from app.services.staff_access_service import StaffAccessService

PROVIDER = uuid4()
SPECIALTY, BRANCH = uuid4(), uuid4()


# ================================================================ admin catalog


class FakeSession:
    def __init__(self, *, fail_commit=False):
        self.fail_commit = fail_commit
        self.events = []

    def commit(self):
        if self.fail_commit:
            raise OperationalError("COMMIT", {}, Exception("connection lost"))
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


class FakeCatalogRepository:
    def __init__(self, session):
        self.session = session
        self.added = []

    def active_specialty_ids(self, provider_id, ids):
        return {SPECIALTY} & set(ids) if provider_id == PROVIDER else set()

    def active_branch_ids(self, provider_id, ids):
        return {BRANCH} & set(ids) if provider_id == PROVIDER else set()

    def active_service_ids(self, provider_id, ids):
        return set()

    def license_exists(self, provider_id, license_number):
        return False

    def doctor_link_ids(self, provider_id, doctor_id):
        return [BRANCH], []

    def add(self, row):
        self.added.append(row)
        self.session.events.append(f"add:{type(row).__name__}")

    def flush(self):
        pass


class FakeIdempotency:
    def __init__(self, *, cached=None, conflict=False):
        self.cached = cached
        self.conflict = conflict
        self.calls = []

    def begin(self, db, *, tenant_id, operation, idempotency_key, payload):
        self.calls.append((tenant_id, operation, idempotency_key))
        if self.conflict:
            raise IdempotencyConflictError("different payload")
        if self.cached is not None:
            return SimpleNamespace(is_replay=True, cached_response=self.cached, record=None)
        return SimpleNamespace(is_replay=False, cached_response=None, record=SimpleNamespace())


DOCTOR = AdminDoctorCreate(
    specialty_id=SPECIALTY,
    full_name_ar="د. اختبار",
    full_name_en="Dr Test",
    branch_ids=[BRANCH],
)


def _catalog(*, fail_commit=False, idempotency=None):
    session = FakeSession(fail_commit=fail_commit)
    repository = FakeCatalogRepository(session)
    return AdminCatalogService(repository, idempotency_service=idempotency), session, repository


def test_doctor_create_stages_audit_before_the_single_commit():
    service, session, _ = _catalog()
    audited = []

    def audit(resource_id):
        audited.append(resource_id)
        session.events.append("audit")

    result = service.create_doctor(provider_id=PROVIDER, data=DOCTOR, audit=audit)

    assert audited == [str(result.id)]
    assert session.events[-2:] == ["audit", "commit"]
    assert session.events.count("commit") == 1


def test_failed_commit_rolls_back_the_write_and_its_audit_together():
    service, session, _ = _catalog(fail_commit=True)
    audited = []

    with pytest.raises(OperationalError):
        service.create_doctor(provider_id=PROVIDER, data=DOCTOR, audit=audited.append)

    # The audit was staged in the same transaction, which was rolled back:
    # the caller gets an error and neither row exists.
    assert len(audited) == 1
    assert session.events[-1] == "rollback"
    assert "commit" not in session.events


def test_failed_audit_prevents_the_write():
    service, session, _ = _catalog()

    def broken_audit(resource_id):
        raise ValueError("audit failed")

    with pytest.raises(ValueError):
        service.create_doctor(provider_id=PROVIDER, data=DOCTOR, audit=broken_audit)

    assert "commit" not in session.events
    assert session.events[-1] == "rollback"


def test_foreign_branch_is_rejected_before_any_write():
    service, session, repository = _catalog()
    data = DOCTOR.model_copy(update={"branch_ids": [uuid4()]})

    with pytest.raises(HTTPException) as exc_info:
        service.create_doctor(provider_id=PROVIDER, data=data)

    assert exc_info.value.detail["code"] == "BRANCH_NOT_FOUND"
    assert repository.added == []
    assert "commit" not in session.events


def test_idempotent_replay_returns_the_first_result_without_writing():
    first, _, _ = _catalog(idempotency=FakeIdempotency())
    created = first.create_doctor(provider_id=PROVIDER, data=DOCTOR, idempotency_key="retry-key-0001")

    idempotency = FakeIdempotency(cached=created.model_dump(mode="json"))
    service, session, repository = _catalog(idempotency=idempotency)
    audited = []

    replayed = service.create_doctor(
        provider_id=PROVIDER, data=DOCTOR, idempotency_key="retry-key-0001", audit=audited.append
    )

    assert replayed.id == created.id
    assert repository.added == []
    assert audited == []
    assert session.events == ["rollback"]
    assert idempotency.calls == [(str(PROVIDER), "admin_create_doctor", "retry-key-0001")]


def test_reused_key_with_different_data_is_409():
    service, session, repository = _catalog(idempotency=FakeIdempotency(conflict=True))

    with pytest.raises(HTTPException) as exc_info:
        service.create_doctor(provider_id=PROVIDER, data=DOCTOR, idempotency_key="retry-key-0001")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "IDEMPOTENCY_CONFLICT"
    assert repository.added == []


def test_without_a_key_idempotency_is_not_used():
    idempotency = FakeIdempotency()
    service, _, repository = _catalog(idempotency=idempotency)

    service.create_doctor(provider_id=PROVIDER, data=DOCTOR)

    assert idempotency.calls == []
    assert repository.added


# ================================================================ login throttle


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_throttle_locks_after_max_failures_and_unlocks_after_window():
    clock = Clock()
    throttle = LoginThrottle(max_failures=3, window_seconds=60, clock=clock)

    for _ in range(3):
        assert throttle.retry_after("Staff@Example.com") is None
        throttle.register_failure(" staff@example.com ")

    assert throttle.retry_after("STAFF@example.com") == 60

    clock.now += 59.5
    assert throttle.retry_after("staff@example.com") == 1

    clock.now += 1
    assert throttle.retry_after("staff@example.com") is None


def test_throttle_reset_and_independent_emails():
    throttle = LoginThrottle(max_failures=2, window_seconds=60, clock=Clock())

    throttle.register_failure("a@example.com")
    throttle.register_failure("a@example.com")
    assert throttle.retry_after("a@example.com") is not None
    assert throttle.retry_after("b@example.com") is None

    throttle.reset("a@example.com")
    assert throttle.retry_after("a@example.com") is None


def test_throttle_memory_is_bounded():
    throttle = LoginThrottle(max_failures=1, window_seconds=60, max_tracked=3, clock=Clock())

    for index in range(10):
        throttle.register_failure(f"user{index}@example.com")

    assert len(throttle._failures) == 3
    assert throttle.retry_after("user9@example.com") is not None
    assert throttle.retry_after("user0@example.com") is None


@pytest.mark.parametrize(
    "kwargs",
    [{"max_failures": 0, "window_seconds": 60}, {"max_failures": 3, "window_seconds": 0}],
)
def test_throttle_rejects_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        LoginThrottle(**kwargs)


class FakeStaffAccess:
    """Stands in for StaffAccessService.authenticate_staff."""

    def __init__(self):
        self.calls = 0
        self.outcome = "invalid"

    def authenticate_staff(self, *, provider_id, email, password):
        self.calls += 1
        if self.outcome == "invalid":
            raise HTTPException(401, {"code": "INVALID_CREDENTIALS", "message": "x"})
        if self.outcome == "no_access":
            raise HTTPException(403, {"code": "STAFF_ACCESS_DENIED", "message": "x"})
        return (
            SimpleNamespace(id=uuid4()),
            SimpleNamespace(id=uuid4(), role="receptionist"),
        )


@pytest.fixture
def login_app(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-signing-key-not-production-0123456789abcdef")
    get_settings.cache_clear()

    throttle = LoginThrottle(max_failures=3, window_seconds=900, clock=Clock())
    access = FakeStaffAccess()

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(id=PROVIDER)
    app.dependency_overrides[deps.get_staff_access_service] = lambda: access
    app.dependency_overrides[login_throttle_module.get_login_throttle] = lambda: throttle

    yield SimpleNamespace(client=TestClient(app), access=access, throttle=throttle)
    get_settings.cache_clear()


def _login(env, email="staff@example.com"):
    return env.client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-ID": "clinic-001"},
        json={"email": email, "password": "wrong"},
    )


def test_login_is_locked_after_repeated_wrong_passwords(login_app):
    statuses = [_login(login_app).status_code for _ in range(3)]
    locked = _login(login_app)

    assert statuses == [401, 401, 401]
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "LOGIN_TEMPORARILY_LOCKED"
    assert int(locked.headers["Retry-After"]) > 0
    # The locked attempt never reaches password verification.
    assert login_app.access.calls == 3
    # Other accounts are unaffected.
    assert _login(login_app, "other@example.com").status_code == 401


def test_successful_login_clears_failures(login_app):
    _login(login_app)
    _login(login_app)
    login_app.access.outcome = "ok"
    assert _login(login_app).status_code == 200

    login_app.access.outcome = "invalid"
    assert [_login(login_app).status_code for _ in range(3)] == [401, 401, 401]


def test_correct_password_without_provider_access_is_not_counted(login_app):
    login_app.access.outcome = "no_access"

    statuses = [_login(login_app).status_code for _ in range(5)]

    assert statuses == [403] * 5


class FakeAuthRepository:
    def __init__(self, user=None):
        self.user = user

    def get_user_by_email(self, *, email):
        return self.user


@pytest.mark.parametrize(
    "user",
    [None, SimpleNamespace(is_active=False, password_hash="x")],
    ids=["unknown", "inactive"],
)
def test_unknown_or_inactive_account_still_runs_a_password_check(monkeypatch, user):
    burned = []
    monkeypatch.setattr(
        "app.services.staff_access_service.burn_password_check",
        lambda password: burned.append(password),
    )

    with pytest.raises(HTTPException) as exc_info:
        StaffAccessService(FakeAuthRepository(user)).authenticate_staff(
            provider_id=PROVIDER, email="nobody@example.com", password="guess"
        )

    assert exc_info.value.detail["code"] == "INVALID_CREDENTIALS"
    assert burned == ["guess"]


def test_burn_password_check_does_real_bcrypt_work():
    passwords._dummy_password_hash.cache_clear()

    passwords.burn_password_check("anything")

    assert passwords._dummy_password_hash().startswith("$2")


# ================================================================ debug route


VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"


@pytest.fixture
def debug_client(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", f"voice_gateway={VOICE_TOKEN}@clinic-001")
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(medmind_ai.router, prefix="/api/v1")
    app.state.medmind_semantic_router = SimpleNamespace(
        route=lambda message, top_k: [SimpleNamespace(name="booking", score=0.9)]
    )

    yield TestClient(app), monkeypatch
    get_settings.cache_clear()


def test_debug_router_requires_the_service_token(debug_client):
    client, _ = debug_client

    response = client.get("/api/v1/ai/debug/router", params={"message": "hi"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "SERVICE_AUTH_REQUIRED"


def test_debug_router_works_in_development_with_the_token(debug_client):
    client, _ = debug_client

    response = client.get(
        "/api/v1/ai/debug/router",
        params={"message": "hi"},
        headers={SERVICE_TOKEN_HEADER: VOICE_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["capability"] == "booking"


@pytest.mark.parametrize("app_env", ["production", "staging", "test"])
def test_debug_router_is_hidden_outside_development(debug_client, app_env):
    client, monkeypatch = debug_client
    monkeypatch.setenv("APP_ENV", app_env)
    get_settings.cache_clear()

    response = client.get(
        "/api/v1/ai/debug/router",
        params={"message": "hi"},
        headers={SERVICE_TOKEN_HEADER: VOICE_TOKEN},
    )

    assert response.status_code == 404


def test_debug_router_rejects_oversized_input(debug_client):
    client, _ = debug_client

    response = client.get(
        "/api/v1/ai/debug/router",
        params={"message": "x" * 501},
        headers={SERVICE_TOKEN_HEADER: VOICE_TOKEN},
    )

    assert response.status_code == 422
