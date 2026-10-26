"""
Lab booking without a doctor - integration tests against a real database.

Opt-in only:  MEDMIND_DB_INTEGRATION=1 and the configured DB_NAME must be
an isolated audit copy (MedMind_Audit*), migrated to f4b8d2c6a1e3.an isolated audit copy (MedMind_Audit*), migrated to the current project head.

Every test runs inside an outer transaction that is rolled back at the end;
the services' own commit()/rollback() calls only touch a SAVEPOINT, so the
database is left unchanged.
"""

import os
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.patient_branch_profile_repository import (
    PatientBranchProfileRepository,
)
from app.repositories.patient_repository import PatientRepository
from app.repositories.working_hours_repository import WorkingHoursRepository
from app.schemas.appointment import (
    AppointmentCancelRequest,
    AppointmentCreateRequest,
    AppointmentRescheduleRequest,
)
from app.schemas.working_hours import SlotGenerationRequest, WorkingHourCreate
from app.services.appointment_service import AppointmentService
from app.services.catalog_service import CatalogService
from app.services.patient_branch_profile_service import (
    PatientBranchProfileService,
)
from app.services.working_hours_service import WorkingHoursService


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1",
    reason="Set MEDMIND_DB_INTEGRATION=1 to run against an audit database.",
)

NATIONAL_ID = "29001011234567"


# ============================================================
# FIXTURES / HELPERS
# ============================================================



APPROVED_SERVER = r"localhost\SQLEXPRESS"
APPROVED_DATABASE = "MedMind_Audit_Final2"
# Every key app/core/config.py may put in the ODBC string; anything else
# (UID/PWD, Initial Catalog, Address, ...) could redirect the connection.
_ALLOWED_ODBC_KEYS = frozenset(
    {"DRIVER", "SERVER", "DATABASE", "TRUSTED_CONNECTION", "ENCRYPT", "TRUSTSERVERCERTIFICATE"}
)


def _odbc_pairs(connect_string: str) -> list[tuple[str, str]]:
    """Split an ODBC connection string into (key, value) pairs.

    Braced values ({...}, with "}}" as an escaped brace) may hold ";".
    Raises ValueError on anything malformed.
    """
    pairs, i, n = [], 0, len(connect_string)
    while i < n:
        while i < n and connect_string[i] in "; \t":
            i += 1
        if i >= n:
            break
        eq = connect_string.find("=", i)
        if eq == -1:
            raise ValueError("segment without '='")
        key, i = connect_string[i:eq].strip(), eq + 1
        if i < n and connect_string[i] == "{":
            i, chars = i + 1, []
            while True:
                if i >= n:
                    raise ValueError("unterminated brace")
                if connect_string[i] == "}":
                    if i + 1 < n and connect_string[i + 1] == "}":
                        chars.append("}")
                        i += 2
                        continue
                    i += 1
                    break
                chars.append(connect_string[i])
                i += 1
            end = connect_string.find(";", i)
            end = n if end == -1 else end
            if connect_string[i:end].strip():
                raise ValueError("text after a braced value")
            value, i = "".join(chars), end + 1
        else:
            end = connect_string.find(";", i)
            end = n if end == -1 else end
            value, i = connect_string[i:end].strip(), end + 1
        if not key:
            raise ValueError("empty key")
        pairs.append((key, value))
    return pairs


def unsafe_engine_target(engine) -> str | None:
    """Why this engine's own target is not the approved audit database, or None.

    Reads only engine.url (the URL the engine will connect with); never
    connects. Reasons name the rule, never a value from the URL.
    """
    url = engine.url
    if url.drivername != "mssql+pyodbc":
        return "not an mssql+pyodbc engine"
    if url.host or url.port or url.database or url.username or url.password or set(url.query) != {"odbc_connect"}:
        return "the engine URL must carry only odbc_connect"
    raw = url.query["odbc_connect"]
    if not isinstance(raw, str):
        return "odbc_connect must appear once"
    try:
        pairs = _odbc_pairs(raw)
    except ValueError:
        return "unparseable ODBC connection string"
    keys = [key.upper() for key, _ in pairs]
    if len(keys) != len(set(keys)):
        return "duplicate ODBC keys"
    if set(keys) - _ALLOWED_ODBC_KEYS:
        return "unexpected ODBC keys"
    values = {key.upper(): value for key, value in pairs}
    if values.get("SERVER") != APPROVED_SERVER:
        return "not the approved server"
    if values.get("DATABASE") != APPROVED_DATABASE:
        return "not the approved database"
    if values.get("TRUSTED_CONNECTION", "").lower() != "yes":
        return "not a Windows Trusted Connection"
    return None


@pytest.fixture
def db_session():
    from app.core.config import get_settings

    settings = get_settings()

    # Refuse unexpected database configuration before opening a connection.
    if (
        settings.db_server != r"localhost\SQLEXPRESS"
        or settings.db_name != "MedMind_Audit_Final2"
        or not settings.db_trusted_connection
    ):
        pytest.fail(
            "SAFETY STOP: tests may connect only to "
            r"localhost\SQLEXPRESS"
            " / MedMind_Audit_Final2 using Windows Trusted Connection."
        )

    from app.db.session import engine

    # The engine was built when app.db.session was first imported and may
    # predate these settings: check the engine's own target, still before
    # opening any connection.
    reason = unsafe_engine_target(engine)
    if reason is not None:
        pytest.fail(f"SAFETY STOP: the engine does not target the approved audit database ({reason}).")

    connection = engine.connect()

    try:
        # Verify the actual database reached by this connection.
        db_name = connection.execute(
            text("SELECT DB_NAME()")
        ).scalar_one()

        # End the implicit transaction opened by the verification query.
        connection.rollback()

        if db_name != "MedMind_Audit_Final2":
            pytest.fail(
                "SAFETY STOP: unexpected connected database "
                f"{db_name!r}"
            )

        # All test writes stay inside this outer transaction.
        outer = connection.begin()

        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

        try:
            yield session
        finally:
            session.close()
            outer.rollback()

    finally:
        connection.close()



class FixedHashProtector:
    """Maps any national ID to one existing patient's stored hash."""

    def __init__(self, national_id_hash: str) -> None:
        self.national_id_hash = national_id_hash

    def hash_national_id(self, national_id: str) -> str:
        return self.national_id_hash


def one(session, sql, **params):
    row = session.execute(text(sql), params).mappings().first()
    assert row is not None, f"missing seed data for: {sql.strip()[:80]}"
    return SimpleNamespace(**row)


def provider(session, tenant_key):
    row = one(
        session,
        "SELECT id, timezone, org_type FROM dbo.providers WHERE tenant_key = :key",
        key=tenant_key,
    )
    row.id = UUID(str(row.id))
    return row


def active_patient_hash(session, provider_id):
    return one(
        session,
        """
        SELECT TOP 1 patient.national_id_hash
        FROM dbo.patient_provider_profiles AS profile
        JOIN dbo.patients AS patient ON patient.id = profile.patient_id
        WHERE profile.provider_id = :provider_id
          AND profile.is_active = 1
          AND patient.is_active = 1
          AND patient.national_id_hash IS NOT NULL
        ORDER BY patient.id
        """,
        provider_id=str(provider_id),
    ).national_id_hash


def active_branch_ids(session, provider_id):
    rows = session.execute(
        text(
            "SELECT id FROM dbo.branches "
            "WHERE provider_id = :provider_id AND is_active = 1 ORDER BY code"
        ),
        {"provider_id": str(provider_id)},
    ).all()
    return [UUID(str(row[0])) for row in rows]


def diagnostic_service_id(session, provider_id):
    return UUID(
        str(
            one(
                session,
                """
                SELECT TOP 1 id FROM dbo.services
                WHERE provider_id = :provider_id AND is_active = 1
                  AND service_type = 'diagnostic'
                ORDER BY code
                """,
                provider_id=str(provider_id),
            ).id
        )
    )


def appointment_service(session, national_id_hash):
    return AppointmentService(
        repository=AppointmentRepository(session),
        patient_repository=PatientRepository(session),
        identity_protector=FixedHashProtector(national_id_hash),
        branch_profile_service=PatientBranchProfileService(
            PatientBranchProfileRepository(session)
        ),
        idempotency_service=None,
    )


def future_date(tz, days=9):
    return datetime.now(ZoneInfo(tz)).date() + timedelta(days=days)


TEST_START = time(6, 0)
TEST_END = time(7, 0)


def own_lab_slots(session, lab, target_date):
    """
    Only the slots created by this test (06:00-07:00). The audit copy may
    also hold MOCK lab-001 opening hours, which must not affect the tests.
    """
    return [
        slot
        for slot in CatalogRepository(session).list_available_slots(
            provider_id=lab.id,
            slot_date=target_date,
            limit=200,
        )
        if TEST_START <= slot.start_time < TEST_END
    ]


def create_lab_slots(session, lab, target_date):
    """Branch-level hours 06:00-07:00 (30 min) at every active lab branch."""

    hours_service = WorkingHoursService(WorkingHoursRepository(session))

    # Materialize slots for hours already configured in the audit copy
    # (MOCK lab-001 hours) first, so the generation below counts only this
    # test's slots whatever the date (rolled back with the test).
    hours_service.generate_slots(
        provider_id=lab.id,
        provider_timezone=lab.timezone,
        data=SlotGenerationRequest(
            date_from=target_date,
            date_to=target_date,
        ),
    )

    for branch_id in active_branch_ids(session, lab.id):
        hour = hours_service.create(
            provider_id=lab.id,
            data=WorkingHourCreate(
                branch_id=branch_id,
                day_of_week=target_date.weekday(),
                start_time=TEST_START,
                end_time=TEST_END,
                slot_duration_minutes=30,
            ),
        )
        assert hour.doctor_id is None

    return hours_service.generate_slots(
        provider_id=lab.id,
        provider_timezone=lab.timezone,
        data=SlotGenerationRequest(
            date_from=target_date,
            date_to=target_date,
        ),
    )


def insert_slot(session, *, provider_id, branch_id, doctor_id, slot_date):
    slot_id = uuid4()
    session.execute(
        text(
            """
            INSERT INTO dbo.doctor_availability_slots (
                id, provider_id, doctor_id, branch_id, working_hours_id,
                slot_date, start_time, end_time, status,
                hold_expires_at, hold_reference, is_waitlist_fill,
                created_at, updated_at
            ) VALUES (
                :id, :provider_id, :doctor_id, :branch_id, NULL,
                :slot_date, '07:00', '07:30', 'available',
                NULL, NULL, 0, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
            )
            """
        ),
        {
            "id": str(slot_id),
            "provider_id": str(provider_id),
            "doctor_id": str(doctor_id) if doctor_id else None,
            "branch_id": str(branch_id),
            "slot_date": slot_date,
        },
    )
    return slot_id


def error_code(exc_info):
    return exc_info.value.detail["code"]


# ============================================================
# LAB: hours -> slots -> catalog -> book -> reschedule -> lookup
# ============================================================


def assign_missing_mrn_codes(session, provider_id):
    """
    Booking requires every branch to have an MRN code. In the audit copy
    lab-001's branches have none (a data gap, unrelated to doctors). Fill
    them inside this test's rolled-back transaction only.
    """
    for index, branch_id in enumerate(active_branch_ids(session, provider_id)):
        session.execute(
            text(
                "UPDATE dbo.branches SET mrn_code = :code "
                "WHERE id = :id AND mrn_code IS NULL"
            ),
            {"code": f"LB{'ABCDEFGHIJ'[index]}", "id": str(branch_id)},
        )


def test_lab_end_to_end_without_doctor(db_session):
    lab = provider(db_session, "lab-001")
    assert lab.org_type == "diagnostic_lab"
    assign_missing_mrn_codes(db_session, lab.id)

    target_date = future_date(lab.timezone)

    generated = create_lab_slots(db_session, lab, target_date)
    branches = active_branch_ids(db_session, lab.id)

    # 2 slots (06:00, 06:30) per branch; the same time at two
    # branches must not collide on the branch-level unique index.
    assert generated.created_slots == 2 * len(branches)

    regenerated = WorkingHoursService(
        WorkingHoursRepository(db_session)
    ).generate_slots(
        provider_id=lab.id,
        provider_timezone=lab.timezone,
        data=SlotGenerationRequest(date_from=target_date, date_to=target_date),
    )
    assert regenerated.created_slots == 0
    assert regenerated.skipped_existing_slots >= 2 * len(branches)

    slots = own_lab_slots(db_session, lab, target_date)
    assert len(slots) == 2 * len(branches)
    assert all(slot.doctor_id is None for slot in slots)
    assert {slot.branch_id for slot in slots} == set(branches)

    service_id = diagnostic_service_id(db_session, lab.id)
    service = appointment_service(
        db_session, active_patient_hash(db_session, lab.id)
    )

    first_slot, second_slot = slots[0], slots[1]

    created = service.create_confirmed_booking(
        provider_id=lab.id,
        provider_timezone=lab.timezone,
        data=AppointmentCreateRequest(
            national_id=NATIONAL_ID,
            slot_id=first_slot.id,
            service_id=service_id,
            channel="web",
        ),
    )
    assert created.status == "confirmed"
    assert created.doctor_name is None
    assert created.service_name

    # Double booking of the same slot is still rejected.
    with pytest.raises(HTTPException) as exc_info:
        service.create_confirmed_booking(
            provider_id=lab.id,
            provider_timezone=lab.timezone,
            data=AppointmentCreateRequest(
                national_id=NATIONAL_ID,
                slot_id=first_slot.id,
                service_id=service_id,
                channel="web",
            ),
        )
    assert exc_info.value.status_code == 409

    rescheduled = service.reschedule_booking(
        provider_id=lab.id,
        provider_timezone=lab.timezone,
        appointment_reference=created.appointment_reference,
        data=AppointmentRescheduleRequest(
            national_id=NATIONAL_ID,
            new_slot_id=second_slot.id,
        ),
    )
    assert rescheduled.doctor_id is None
    assert rescheduled.new_slot_id == second_slot.id

    details = service.get_booking_by_reference(
        provider_id=lab.id,
        appointment_reference=created.appointment_reference,
    )
    assert details.doctor_id is None
    assert details.doctor_name is None
    assert details.service_id == service_id

    statuses = dict(
        db_session.execute(
            text(
                "SELECT id, status FROM dbo.doctor_availability_slots "
                "WHERE id IN (:a, :b)"
            ),
            {"a": str(first_slot.id), "b": str(second_slot.id)},
        ).all()
    )
    statuses = {UUID(str(k)): v for k, v in statuses.items()}
    assert statuses[first_slot.id] == "available"
    assert statuses[second_slot.id] == "booked"


def test_lab_slot_rejects_service_of_another_provider(db_session):
    lab = provider(db_session, "lab-001")
    other_lab = provider(db_session, "lab-002")
    target_date = future_date(lab.timezone)

    create_lab_slots(db_session, lab, target_date)
    slot = own_lab_slots(db_session, lab, target_date)[0]

    service = appointment_service(
        db_session, active_patient_hash(db_session, lab.id)
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_confirmed_booking(
            provider_id=lab.id,
            provider_timezone=lab.timezone,
            data=AppointmentCreateRequest(
                national_id=NATIONAL_ID,
                slot_id=slot.id,
                service_id=diagnostic_service_id(db_session, other_lab.id),
                channel="web",
            ),
        )
    assert error_code(exc_info) == "LAB_SLOT_SERVICE_MISMATCH"


def test_lab_slot_is_invisible_and_unbookable_for_other_tenant(db_session):
    lab = provider(db_session, "lab-001")
    clinic = provider(db_session, "clinic-001")
    target_date = future_date(lab.timezone)

    create_lab_slots(db_session, lab, target_date)
    lab_slot = own_lab_slots(db_session, lab, target_date)[0]

    clinic_slots = CatalogRepository(db_session).list_available_slots(
        provider_id=clinic.id, slot_date=target_date
    )
    assert lab_slot.id not in {slot.id for slot in clinic_slots}

    service = appointment_service(
        db_session, active_patient_hash(db_session, clinic.id)
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_confirmed_booking(
            provider_id=clinic.id,
            provider_timezone=clinic.timezone,
            data=AppointmentCreateRequest(
                national_id=NATIONAL_ID,
                slot_id=lab_slot.id,
                service_id=diagnostic_service_id(db_session, clinic.id),
                channel="web",
            ),
        )
    assert error_code(exc_info) == "SLOT_NOT_FOUND"


def slot_status(session, slot_id):
    return session.execute(
        text("SELECT status FROM dbo.doctor_availability_slots WHERE id = :id"),
        {"id": str(slot_id)},
    ).scalar()


def test_lab_configured_branch_slots_book_reject_cancel(db_session):
    """
    Uses the lab-001 branch schedule already configured in the audit copy
    (07_lab001_branch_booking_setup.sql, MOCK data): list -> book ->
    no doctor + slot booked -> same slot rejected -> cancel releases it.
    """
    lab = provider(db_session, "lab-001")
    now = datetime.now(ZoneInfo(lab.timezone))

    configured = db_session.execute(
        text(
            """
            SELECT TOP 1 slot.slot_date
            FROM dbo.doctor_availability_slots AS slot
            WHERE slot.provider_id = :provider_id
              AND slot.doctor_id IS NULL
              AND slot.status = 'available'
              AND slot.slot_date > :today
            ORDER BY slot.slot_date
            """
        ),
        {"provider_id": str(lab.id), "today": now.date()},
    ).scalar()
    if configured is None:
        pytest.skip("lab-001 has no configured branch-level slots in this DB.")

    slots = CatalogRepository(db_session).list_available_slots(
        provider_id=lab.id,
        slot_date=configured,
        limit=200,
    )
    assert slots
    assert all(slot.doctor_id is None for slot in slots)
    assert len({slot.branch_id for slot in slots}) == len(
        active_branch_ids(db_session, lab.id)
    )

    slot = slots[0]
    service = appointment_service(
        db_session, active_patient_hash(db_session, lab.id)
    )
    request = AppointmentCreateRequest(
        national_id=NATIONAL_ID,
        slot_id=slot.id,
        service_id=diagnostic_service_id(db_session, lab.id),
        channel="web",
    )

    created = service.create_confirmed_booking(
        provider_id=lab.id,
        provider_timezone=lab.timezone,
        data=request,
    )
    assert created.status == "confirmed"
    assert created.doctor_name is None

    stored = db_session.execute(
        text(
            "SELECT doctor_id, slot_id, branch_id, status FROM dbo.appointments "
            "WHERE provider_id = :provider_id AND appointment_reference = :ref"
        ),
        {"provider_id": str(lab.id), "ref": created.appointment_reference},
    ).mappings().one()
    assert stored["doctor_id"] is None
    assert UUID(str(stored["slot_id"])) == slot.id
    assert UUID(str(stored["branch_id"])) == slot.branch_id
    assert stored["status"] == "confirmed"

    assert slot_status(db_session, slot.id) == "booked"
    remaining = CatalogRepository(db_session).list_available_slots(
        provider_id=lab.id, slot_date=configured, limit=200
    )
    assert slot.id not in {item.id for item in remaining}

    with pytest.raises(HTTPException) as exc_info:
        service.create_confirmed_booking(
            provider_id=lab.id,
            provider_timezone=lab.timezone,
            data=request,
        )
    assert exc_info.value.status_code == 409

    cancelled = service.cancel_booking(
        provider_id=lab.id,
        appointment_reference=created.appointment_reference,
        data=AppointmentCancelRequest(
            national_id=NATIONAL_ID,
            reason="e2e test",
        ),
    )
    assert cancelled.previous_status == "confirmed"
    assert slot_status(db_session, slot.id) == "available"

    released = CatalogRepository(db_session).list_available_slots(
        provider_id=lab.id, slot_date=configured, limit=200
    )
    assert slot.id in {item.id for item in released}


# ============================================================
# CLINIC / HOSPITAL: doctor stays mandatory
# ============================================================


@pytest.mark.parametrize("tenant_key", ["clinic-001", "hospital-001"])
def test_clinic_and_hospital_hours_require_doctor(db_session, tenant_key):
    tenant = provider(db_session, tenant_key)
    branch_id = active_branch_ids(db_session, tenant.id)[0]

    with pytest.raises(HTTPException) as exc_info:
        WorkingHoursService(WorkingHoursRepository(db_session)).create(
            provider_id=tenant.id,
            data=WorkingHourCreate(
                branch_id=branch_id,
                day_of_week=0,
                start_time=time(6, 0),
                end_time=time(7, 0),
            ),
        )
    assert error_code(exc_info) == "DOCTOR_REQUIRED"


def test_clinic_doctorless_slot_is_hidden_and_unbookable(db_session):
    clinic = provider(db_session, "clinic-001")
    target_date = future_date(clinic.timezone)
    slot_id = insert_slot(
        db_session,
        provider_id=clinic.id,
        branch_id=active_branch_ids(db_session, clinic.id)[0],
        doctor_id=None,
        slot_date=target_date,
    )

    listed = CatalogRepository(db_session).list_available_slots(
        provider_id=clinic.id, slot_date=target_date
    )
    assert slot_id not in {slot.id for slot in listed}

    service = appointment_service(
        db_session, active_patient_hash(db_session, clinic.id)
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_confirmed_booking(
            provider_id=clinic.id,
            provider_timezone=clinic.timezone,
            data=AppointmentCreateRequest(
                national_id=NATIONAL_ID,
                slot_id=slot_id,
                service_id=diagnostic_service_id(db_session, clinic.id),
                channel="web",
            ),
        )
    assert error_code(exc_info) == "LAB_SLOT_SERVICE_MISMATCH"


def test_clinic_doctor_booking_unchanged(db_session):
    clinic = provider(db_session, "clinic-001")
    tomorrow = future_date(clinic.timezone, days=1)

    # An active doctor/branch/service combination; the slot is created by
    # this test (rolled back) so the test does not depend on how far the
    # seeded slots of the audit copy reach.
    pair = one(
        db_session,
        """
        SELECT TOP 1 doctor.id AS doctor_id, db.branch_id, ds.service_id
        FROM dbo.doctors AS doctor
        JOIN dbo.doctor_branches AS db
            ON db.doctor_id = doctor.id AND db.provider_id = doctor.provider_id
           AND db.is_active = 1
        JOIN dbo.branches AS branch
            ON branch.id = db.branch_id AND branch.provider_id = doctor.provider_id
           AND branch.is_active = 1
        JOIN dbo.doctor_services AS ds
            ON ds.doctor_id = doctor.id AND ds.provider_id = doctor.provider_id
           AND ds.is_active = 1
        JOIN dbo.services AS service
            ON service.id = ds.service_id AND service.provider_id = doctor.provider_id
           AND service.is_active = 1
        WHERE doctor.provider_id = :provider_id
          AND doctor.is_active = 1
          AND NOT EXISTS (
              SELECT 1 FROM dbo.doctor_availability_slots AS slot
              WHERE slot.doctor_id = doctor.id
                AND slot.slot_date = :tomorrow
                AND slot.start_time = '07:00'
          )
        ORDER BY doctor.id, db.branch_id, ds.service_id
        """,
        provider_id=str(clinic.id),
        tomorrow=tomorrow,
    )
    pair.slot_id = insert_slot(
        db_session,
        provider_id=clinic.id,
        branch_id=UUID(str(pair.branch_id)),
        doctor_id=UUID(str(pair.doctor_id)),
        slot_date=tomorrow,
    )

    service = appointment_service(
        db_session, active_patient_hash(db_session, clinic.id)
    )

    created = service.create_confirmed_booking(
        provider_id=clinic.id,
        provider_timezone=clinic.timezone,
        data=AppointmentCreateRequest(
            national_id=NATIONAL_ID,
            slot_id=UUID(str(pair.slot_id)),
            service_id=UUID(str(pair.service_id)),
            channel="web",
        ),
    )
    assert created.status == "confirmed"
    assert created.doctor_name

    details = service.get_booking_by_reference(
        provider_id=clinic.id,
        appointment_reference=created.appointment_reference,
    )
    assert details.doctor_id == UUID(str(pair.doctor_id))


def test_doctor_service_mismatch_still_rejected(db_session):
    # Any clinic/hospital slot whose doctor does not offer some active
    # service of the same provider.
    row = one(
        db_session,
        """
        SELECT TOP 1 slot.id AS slot_id, other.id AS service_id,
               provider.tenant_key
        FROM dbo.doctor_availability_slots AS slot
        JOIN dbo.providers AS provider
            ON provider.id = slot.provider_id
           AND provider.org_type IN ('clinic', 'hospital')
        JOIN dbo.doctors AS doctor
            ON doctor.id = slot.doctor_id AND doctor.is_active = 1
        JOIN dbo.doctor_branches AS db
            ON db.doctor_id = slot.doctor_id AND db.branch_id = slot.branch_id
           AND db.is_active = 1
        JOIN dbo.branches AS branch
            ON branch.id = slot.branch_id AND branch.is_active = 1
        JOIN dbo.services AS other
            ON other.provider_id = slot.provider_id AND other.is_active = 1
        WHERE slot.status = 'available'
          AND slot.slot_date >= DATEADD(day, 1, CAST(SYSDATETIME() AS date))
          AND NOT EXISTS (
              SELECT 1 FROM dbo.doctor_services AS ds
              WHERE ds.doctor_id = slot.doctor_id
                AND ds.service_id = other.id AND ds.is_active = 1
          )
        ORDER BY slot.slot_date, slot.start_time
        """,
    )
    clinic = provider(db_session, row.tenant_key)

    service = appointment_service(
        db_session, active_patient_hash(db_session, clinic.id)
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_confirmed_booking(
            provider_id=clinic.id,
            provider_timezone=clinic.timezone,
            data=AppointmentCreateRequest(
                national_id=NATIONAL_ID,
                slot_id=UUID(str(row.slot_id)),
                service_id=UUID(str(row.service_id)),
                channel="web",
            ),
        )
    assert error_code(exc_info) == "DOCTOR_SERVICE_MISMATCH"


# ============================================================
# PUBLIC CATALOG
# ============================================================


def test_public_catalog_lists_labs(db_session):
    catalog = CatalogService(CatalogRepository(db_session))

    labs = catalog.get_public_providers(org_type="diagnostic_lab")
    assert labs
    assert all(item.org_type == "diagnostic_lab" for item in labs)

    lab = provider(db_session, "lab-001")
    assert catalog.get_public_provider(provider_id=lab.id) is not None
