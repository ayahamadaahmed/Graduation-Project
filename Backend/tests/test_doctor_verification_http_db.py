"""
Doctor verification over HTTP against a real database - opt-in.

Opt-in only: MEDMIND_DB_INTEGRATION=1, plus APP_ENV=staging and DB_SERVER /
DB_NAME / DB_TRUSTED_CONNECTION set explicitly to localhost\\SQLEXPRESS /
MedMind_Audit_Final2 / true. Every connection goes through
test_doctor_verification_concurrency_db.guarded_session: the fail-closed
target guard before connecting, SELECT DB_NAME() after, one outer
transaction that is always rolled back, and the connection discarded.

What is real: the admin_catalog routes, get_current_provider (provider
lookup by X-Tenant-ID), require_staff_roles, AdminCatalogService and its
repository, StaffAuditService and its repository, and the services' own
commit()/rollback(). Only authentication is replaced: get_current_staff
returns a StaffContext built from a committed provider_admin membership
(the real JWT path is covered offline in test_doctor_verification.py).

Every request of a test shares one guarded Session. A service's commit()
only releases a SAVEPOINT, so its changes are visible to the next request
and to the assertions of the same test, and are never committed.

Not covered here, because it cannot be rolled back or verified in-process:
a real commit and its durability, a running backend over the network, real
JWT resolution against user_accounts, and a booking after a committed
rejection.
"""

import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api import dependencies as deps
from app.api.routers import admin_catalog
from app.core.config import get_settings, staging_selected
from app.security.staff_context import StaffContext
from tests.test_doctor_verification_concurrency_db import (
    committed_status,
    guarded_session,
    sql_error_numbers,
)


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1",
    reason="Set MEDMIND_DB_INTEGRATION=1 to run against an audit database.",
)

REASON = "Licence could not be confirmed with the syndicate."
FOREIGN_KEY_VIOLATION = 547  # SQL Server error number


@pytest.fixture(autouse=True)
def enforcement_stays_off():
    """These tests never need enforcement: fail closed if it is on."""
    if not staging_selected():
        pytest.fail("SAFETY STOP: APP_ENV=staging is required for these tests.")
    get_settings.cache_clear()
    if get_settings().doctor_verification_enforced:
        pytest.fail("SAFETY STOP: DOCTOR_VERIFICATION_ENFORCED must be false for these tests.")
    yield
    get_settings.cache_clear()


# ============================================================ committed seed data

# An active, verified doctor of an active provider that has an active
# provider_admin (the reviewer: the decision's composite foreign key needs a
# real membership row).
SEED_SQL = """
SELECT TOP 1
    doctor.id AS doctor_id, provider.id AS provider_id, provider.tenant_key,
    membership.id AS membership_id, membership.user_id
FROM dbo.doctors AS doctor
JOIN dbo.providers AS provider
    ON provider.id = doctor.provider_id AND provider.is_active = 1
JOIN dbo.provider_memberships AS membership
    ON membership.provider_id = provider.id
    AND membership.role = 'provider_admin' AND membership.is_active = 1
WHERE doctor.is_active = 1 AND doctor.verification_status = 'verified'
ORDER BY provider.tenant_key, doctor.id, membership.id
"""

# Another active provider with an active provider_admin (tenant isolation).
OTHER_PROVIDER_SQL = """
SELECT TOP 1
    provider.id AS provider_id, provider.tenant_key,
    membership.id AS membership_id, membership.user_id
FROM dbo.providers AS provider
JOIN dbo.provider_memberships AS membership
    ON membership.provider_id = provider.id
    AND membership.role = 'provider_admin' AND membership.is_active = 1
WHERE provider.is_active = 1 AND provider.id <> :provider_id
ORDER BY provider.tenant_key, membership.id
"""


def _admin(row):
    return StaffContext(
        user_id=UUID(str(row["user_id"])), membership_id=UUID(str(row["membership_id"])),
        provider_id=UUID(str(row["provider_id"])), role="provider_admin", doctor_id=None,
    )


def _committed_decision_count(doctor_id):
    with guarded_session() as db:
        return db.session.execute(
            text("SELECT COUNT(*) FROM dbo.doctor_verification_decisions WHERE doctor_id = :id"),
            {"id": str(doctor_id)},
        ).scalar_one()


@pytest.fixture
def world():
    """The real routes on one guarded, always rolled-back connection."""
    with guarded_session() as db:
        # Seed reads on the connection, before the Session's first statement
        # (and so before any SAVEPOINT a service could roll back to).
        seed = db.connection.execute(text(SEED_SQL)).mappings().first()
        if seed is None:
            pytest.skip("No committed active, verified doctor whose provider has an active provider_admin.")
        other = db.connection.execute(
            text(OTHER_PROVIDER_SQL), {"provider_id": str(seed["provider_id"])},
        ).mappings().first()
        if other is None:
            pytest.skip("No second active provider with an active provider_admin.")

        state = SimpleNamespace(
            db=db,
            doctor=SimpleNamespace(id=UUID(str(seed["doctor_id"])), provider_id=UUID(str(seed["provider_id"]))),
            tenant=seed["tenant_key"],
            admin=_admin(seed),
            other_tenant=other["tenant_key"],
            other_admin=_admin(other),
        )
        state.staff = state.admin
        committed_decisions_before = _committed_decision_count(state.doctor.id)

        app = FastAPI()
        app.include_router(admin_catalog.router, prefix="/api/v1")
        # Every database dependency of the routes gets this test's guarded Session.
        app.dependency_overrides[deps.get_db_session] = lambda: db.session
        app.dependency_overrides[deps.get_current_staff] = lambda: state.staff
        state.client = TestClient(app, raise_server_exceptions=False)
        state.raising_client = TestClient(app, raise_server_exceptions=True)

        state.baseline = SimpleNamespace(decisions=decisions(state), audits=audits(state))
        yield state

    # Rolled back: nothing reached the committed state.
    assert committed_status(state.doctor) == "verified"
    assert _committed_decision_count(state.doctor.id) == committed_decisions_before


def _sorted(rows):
    # Rows hold None (reason, patient_id): order by repr, never compare None with str.
    return sorted(rows, key=repr)


def verify(world, body, *, tenant=None, client=None):
    return (client or world.client).post(
        f"/api/v1/admin/doctors/{world.doctor.id}/verification", json=body,
        headers={"X-Tenant-ID": tenant or world.tenant},
    )


def resubmit(world, *, tenant=None):
    return world.client.post(
        f"/api/v1/admin/doctors/{world.doctor.id}/resubmit",
        headers={"X-Tenant-ID": tenant or world.tenant},
    )


def doctor_status(world):
    return world.db.session.execute(
        text("SELECT verification_status FROM dbo.doctors WHERE id = :id"), {"id": str(world.doctor.id)},
    ).scalar_one()


def decisions(world):
    """This doctor's decision rows visible in the test's transaction."""
    rows = world.db.session.execute(
        text(
            "SELECT decision, previous_status, reason, provider_id, reviewer_user_id, reviewer_membership_id "
            "FROM dbo.doctor_verification_decisions WHERE doctor_id = :id"
        ),
        {"id": str(world.doctor.id)},
    ).all()
    return _sorted((r[0], r[1], r[2], UUID(str(r[3])), UUID(str(r[4])), UUID(str(r[5]))) for r in rows)


def audits(world):
    """Audit rows about this doctor visible in the test's transaction."""
    rows = world.db.session.execute(
        text(
            "SELECT action, outcome, resource_type, provider_id, user_id, membership_id, patient_id "
            "FROM dbo.staff_audit_logs WHERE resource_type = 'doctor' AND resource_id = :id"
        ),
        {"id": str(world.doctor.id)},
    ).all()
    return _sorted((r[0], r[1], r[2], UUID(str(r[3])), UUID(str(r[4])), UUID(str(r[5])), r[6]) for r in rows)


def new_rows(world):
    return (
        [row for row in decisions(world) if row not in world.baseline.decisions],
        [row for row in audits(world) if row not in world.baseline.audits],
    )


def _decision(world, decision, previous, reason=None, staff=None):
    staff = staff or world.admin
    return (decision, previous, reason, world.doctor.provider_id, staff.user_id, staff.membership_id)


def _audit(world, action, staff=None):
    staff = staff or world.admin
    return (action, "success", "doctor", world.doctor.provider_id, staff.user_id, staff.membership_id, None)


# ============================================================ tests


def test_reject_resubmit_verify_persist_status_history_and_audit(world):
    rejected = verify(world, {"decision": "rejected", "reason": f"  {REASON}  "})
    assert rejected.status_code == 200
    assert rejected.json()["verification_status"] == "rejected"
    assert "reason" not in rejected.json()
    assert doctor_status(world) == "rejected"

    resubmitted = resubmit(world)
    assert resubmitted.status_code == 200
    assert resubmitted.json()["verification_status"] == "pending"
    assert doctor_status(world) == "pending"

    verified = verify(world, {"decision": "verified"})
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"
    assert doctor_status(world) == "verified"

    new_decisions, new_audits = new_rows(world)
    assert new_decisions == _sorted([
        _decision(world, "rejected", "verified", REASON),  # stored trimmed
        _decision(world, "resubmitted", "rejected"),
        _decision(world, "verified", "pending"),
    ])
    assert new_audits == _sorted([
        _audit(world, "doctor.reject"), _audit(world, "doctor.resubmit"), _audit(world, "doctor.verify"),
    ])


def test_invalid_transitions_and_no_ops_write_nothing(world):
    # On the committed 'verified' doctor.
    assert verify(world, {"decision": "verified"}).status_code == 200  # no-op
    conflict = resubmit(world)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "DOCTOR_VERIFICATION_CONFLICT"
    assert verify(world, {"decision": "rejected"}).status_code == 422  # reason required
    assert new_rows(world) == ([], [])
    assert doctor_status(world) == "verified"

    assert verify(world, {"decision": "rejected", "reason": REASON}).status_code == 200
    for body in ({"decision": "rejected", "reason": REASON}, {"decision": "verified"}):
        response = verify(world, body)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "DOCTOR_VERIFICATION_CONFLICT"

    # Only the one real rejection was recorded.
    assert new_rows(world) == (
        [_decision(world, "rejected", "verified", REASON)], [_audit(world, "doctor.reject")],
    )
    assert doctor_status(world) == "rejected"


def test_a_failed_decision_insert_rolls_back_the_status_change(world):
    # A reviewer whose user does not own the membership: the decision's
    # composite foreign key refuses it after the status UPDATE has run.
    world.staff = StaffContext(
        user_id=uuid4(), membership_id=world.admin.membership_id,
        provider_id=world.admin.provider_id, role="provider_admin", doctor_id=None,
    )

    with pytest.raises(IntegrityError) as error:
        verify(world, {"decision": "rejected", "reason": REASON}, client=world.raising_client)
    assert FOREIGN_KEY_VIOLATION in sql_error_numbers(error.value)
    assert verify(world, {"decision": "rejected", "reason": REASON}).status_code == 500

    # The service rolled back its SAVEPOINT: status, history and audit unchanged.
    assert doctor_status(world) == "verified"
    assert new_rows(world) == ([], [])

    # The transaction is still usable: the real reviewer succeeds afterwards.
    world.staff = world.admin
    assert verify(world, {"decision": "rejected", "reason": REASON}).status_code == 200
    assert new_rows(world) == (
        [_decision(world, "rejected", "verified", REASON)], [_audit(world, "doctor.reject")],
    )


def test_another_providers_admin_cannot_see_or_change_the_doctor(world):
    world.staff = world.other_admin

    for response in (
        verify(world, {"decision": "rejected", "reason": REASON}, tenant=world.other_tenant),
        resubmit(world, tenant=world.other_tenant),
    ):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "DOCTOR_NOT_FOUND"

    assert doctor_status(world) == "verified"
    assert new_rows(world) == ([], [])


def test_an_unknown_tenant_is_404_from_the_real_provider_lookup(world):
    response = verify(world, {"decision": "verified"}, tenant=f"unknown-{uuid4().hex[:8]}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PROVIDER_NOT_FOUND"
    assert new_rows(world) == ([], [])
