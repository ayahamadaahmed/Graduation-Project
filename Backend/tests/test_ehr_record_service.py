from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas.staff_ehr import ClinicalNoteCreateRequest
from app.security.staff_context import StaffContext
from app.repositories.ehr_record_repository import CARE_RELATIONSHIP_APPOINTMENT_STATUSES
from app.services.ehr_record_service import EHRRecordService

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


# ============================================================
# FAKES
# ============================================================
class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRepository:
    """In-memory stand-in for EHRRecordRepository that honours provider scoping."""

    def __init__(self):
        self.session = FakeSession()
        self.profiles = set()          # (patient_id, provider_id)
        self.encounters = {}           # id -> encounter
        self.appointments = []         # SimpleNamespace(provider_id, patient_id, doctor_id, status)
        self.notes = {}                # id -> ClinicalNote
        self.calls = []                # every provider_id the service asked about
        self.conditions = []
        self.allergies = []
        self.medications = []
        self.visit_rows = []
        self.report_rows = []
        self.lab = {}
        self.radiology = {}

    def _seen(self, provider_id):
        self.calls.append(provider_id)

    def get_active_profile(self, *, patient_id, provider_id):
        self._seen(provider_id)
        return object() if (patient_id, provider_id) in self.profiles else None

    def doctor_has_care_relationship(self, *, provider_id, patient_id, doctor_id):
        self._seen(provider_id)
        by_encounter = any(
            e.provider_id == provider_id and e.patient_id == patient_id and e.doctor_id == doctor_id
            for e in self.encounters.values()
        )
        by_appointment = any(
            a.provider_id == provider_id and a.patient_id == patient_id
            and a.doctor_id == doctor_id and a.status in CARE_RELATIONSHIP_APPOINTMENT_STATUSES
            for a in self.appointments
        )
        return by_encounter or by_appointment

    def list_conditions(self, *, provider_id, patient_id):
        self._seen(provider_id)
        return self.conditions

    def list_allergies(self, *, provider_id, patient_id):
        self._seen(provider_id)
        return self.allergies

    def list_medications(self, *, provider_id, patient_id):
        self._seen(provider_id)
        return self.medications

    def list_visits(self, *, provider_id, patient_id, limit, offset):
        self._seen(provider_id)
        return self.visit_rows, len(self.visit_rows)

    def get_encounter(self, *, provider_id, patient_id, encounter_id):
        self._seen(provider_id)
        enc = self.encounters.get(encounter_id)
        if enc and enc.provider_id == provider_id and enc.patient_id == patient_id:
            return enc
        return None

    def list_reports(self, *, provider_id, patient_id, report_type, limit, offset):
        self._seen(provider_id)
        return self.report_rows, len(self.report_rows)

    def get_lab_report(self, *, provider_id, patient_id, report_id):
        self._seen(provider_id)
        return self.lab.get(report_id)

    def get_radiology_report(self, *, provider_id, patient_id, report_id):
        self._seen(provider_id)
        return self.radiology.get(report_id)

    def list_notes(self, *, provider_id, patient_id, encounter_id, limit, offset):
        self._seen(provider_id)
        rows = [
            SimpleNamespace(ClinicalNote=n, doctor_name_en="Dr. A", doctor_name_ar="د. أ")
            for n in self.notes.values()
            if n.provider_id == provider_id and n.patient_id == patient_id
        ]
        return rows, len(rows)

    def get_note(self, *, provider_id, patient_id, note_id):
        self._seen(provider_id)
        n = self.notes.get(note_id)
        if n and n.provider_id == provider_id and n.patient_id == patient_id:
            return SimpleNamespace(ClinicalNote=n, doctor_name_en="Dr. A", doctor_name_ar="د. أ")
        return None

    def get_note_for_update(self, *, provider_id, patient_id, note_id):
        self._seen(provider_id)
        n = self.notes.get(note_id)
        if n and n.provider_id == provider_id and n.patient_id == patient_id:
            return n
        return None

    def add_note(self, note):
        self.notes[note.id] = note
        return note


def staff(role="doctor", provider_id=None, doctor_id="auto"):
    return StaffContext(
        user_id=uuid4(),
        membership_id=uuid4(),
        provider_id=provider_id or uuid4(),
        role=role,
        doctor_id=(uuid4() if doctor_id == "auto" else doctor_id),
    )


class World:
    """One provider, one patient registered there, one visit by `doctor`."""

    def __init__(self, with_encounter_doctor=True):
        self.repo = FakeRepository()
        self.service = EHRRecordService(self.repo)
        self.provider_id = uuid4()
        self.patient_id = uuid4()
        self.doctor = staff("doctor", self.provider_id)
        self.repo.profiles.add((self.patient_id, self.provider_id))
        self.encounter = SimpleNamespace(
            id=uuid4(),
            provider_id=self.provider_id,
            patient_id=self.patient_id,
            doctor_id=self.doctor.doctor_id if with_encounter_doctor else None,
        )
        self.repo.encounters[self.encounter.id] = self.encounter

    def note_request(self, **overrides):
        data = {"encounter_id": self.encounter.id, "note_text": "Stable. Continue therapy."}
        data.update(overrides)
        return ClinicalNoteCreateRequest(**data)


def code_of(exc_info):
    return exc_info.value.detail["code"]


# ============================================================
# TENANT ISOLATION / PATIENT ACCESS
# ============================================================
def test_patient_not_registered_at_provider_is_404_everywhere():
    w = World()
    stranger = staff("doctor", uuid4())  # another provider's doctor

    calls = [
        lambda: w.service.get_medical_history(staff=stranger, patient_id=w.patient_id),
        lambda: w.service.list_visits(staff=stranger, patient_id=w.patient_id, limit=10, offset=0),
        lambda: w.service.list_reports(staff=stranger, patient_id=w.patient_id, report_type=None, limit=10, offset=0),
        lambda: w.service.list_notes(staff=stranger, patient_id=w.patient_id, encounter_id=None, limit=10, offset=0),
        lambda: w.service.get_note(staff=stranger, patient_id=w.patient_id, note_id=uuid4()),
        lambda: w.service.create_note(staff=stranger, patient_id=w.patient_id, data=w.note_request()),
    ]

    for call in calls:
        with pytest.raises(HTTPException) as exc_info:
            call()

        assert exc_info.value.status_code == 404
        assert code_of(exc_info) == "PATIENT_NOT_FOUND"


def test_service_only_ever_queries_the_callers_provider():
    w = World()

    w.service.get_medical_history(staff=w.doctor, patient_id=w.patient_id)
    w.service.list_visits(staff=w.doctor, patient_id=w.patient_id, limit=10, offset=0)

    assert set(w.repo.calls) == {w.provider_id}


# ============================================================
# READ MAPPING
# ============================================================
def test_medical_history_is_returned_in_three_groups():
    w = World()
    w.repo.conditions = [
        SimpleNamespace(
            id=uuid4(), condition_name="Hypertension", icd10_code="I10", clinical_status="active",
            severity="moderate", onset_date=date(2022, 1, 1), resolved_date=None, notes=None,
            encounter_id=None, recorded_by_doctor_id=None, created_at=NOW,
        )
    ]
    w.repo.allergies = [
        SimpleNamespace(
            id=uuid4(), allergen="Penicillin", allergen_type="drug", reaction="Rash", severity="moderate",
            status="active", noted_date=None, encounter_id=None, recorded_by_doctor_id=None, created_at=NOW,
        )
    ]
    w.repo.medications = [
        SimpleNamespace(
            id=uuid4(), medication_name="Amlodipine", dosage="5 mg", frequency="Once daily", route="oral",
            start_date=None, end_date=None, status="active", notes=None, encounter_id=None,
            prescribed_by_doctor_id=None, created_at=NOW,
        )
    ]

    result = w.service.get_medical_history(staff=w.doctor, patient_id=w.patient_id)

    assert result.patient_id == w.patient_id
    assert [c.condition_name for c in result.conditions] == ["Hypertension"]
    assert [a.allergen for a in result.allergies] == ["Penicillin"]
    assert [m.medication_name for m in result.medications] == ["Amlodipine"]


def test_visits_include_doctor_and_branch_names():
    w = World()
    enc = SimpleNamespace(
        id=uuid4(), encounter_type="outpatient_visit", status="closed", started_at=NOW, ended_at=None,
        doctor_id=uuid4(), branch_id=uuid4(), appointment_id=None,
    )
    w.repo.visit_rows = [
        SimpleNamespace(
            EHREncounter=enc, doctor_name_en="Dr. Salma", doctor_name_ar="د. سلمى",
            branch_name_en="Downtown", branch_name_ar="وسط البلد",
        )
    ]

    result = w.service.list_visits(staff=w.doctor, patient_id=w.patient_id, limit=10, offset=0)

    assert result.total == 1
    assert result.items[0].doctor_name_en == "Dr. Salma"
    assert result.items[0].branch_name_ar == "وسط البلد"


def test_lab_report_detail_converts_numbers_and_unreadable_fields():
    w = World()
    report_id = uuid4()
    report = SimpleNamespace(
        id=report_id, encounter_id=None, document_type="cbc", status="processed",
        unreadable_fields_json='["MCV"]', created_at=NOW,
    )
    from decimal import Decimal
    result_row = SimpleNamespace(
        result_index=0, panel="cbc", raw_name="Hemoglobin", canonical_name="hemoglobin",
        value=Decimal("12.350000"), unit="g/dL", reference_min=Decimal("11"), reference_max=Decimal("16"),
        reference_text="11 - 16", flag="normal", mapping_status="mapped",
    )
    w.repo.lab[report_id] = (report, [result_row])

    detail = w.service.get_lab_report(staff=w.doctor, patient_id=w.patient_id, report_id=report_id)

    assert detail.unreadable_fields == ["MCV"]
    assert detail.results[0].value == 12.35
    assert detail.results[0].reference_max == 16.0


def test_unknown_report_is_404():
    w = World()

    with pytest.raises(HTTPException) as exc_info:
        w.service.get_lab_report(staff=w.doctor, patient_id=w.patient_id, report_id=uuid4())

    assert code_of(exc_info) == "REPORT_NOT_FOUND"

    with pytest.raises(HTTPException) as exc_info:
        w.service.get_radiology_report(staff=w.doctor, patient_id=w.patient_id, report_id=uuid4())

    assert code_of(exc_info) == "REPORT_NOT_FOUND"


def test_radiology_detail_survives_malformed_json():
    w = World()
    report_id = uuid4()
    report = SimpleNamespace(id=report_id, encounter_id=None, modality="chest_xray", status="processed", created_at=NOW)
    from decimal import Decimal
    assessment = SimpleNamespace(
        assessment_type="chest_xray", classification="normal", confidence=Decimal("0.93"),
        probabilities_json="not json", model_name="m", model_version="1", limitations_json='["Not a diagnosis"]',
        created_at=NOW,
    )
    w.repo.radiology[report_id] = (report, [assessment])

    detail = w.service.get_radiology_report(staff=w.doctor, patient_id=w.patient_id, report_id=report_id)

    assert detail.assessments[0].probabilities == {}
    assert detail.assessments[0].limitations == ["Not a diagnosis"]
    assert detail.assessments[0].confidence == 0.93


# ============================================================
# CREATING NOTES
# ============================================================
def test_only_doctors_can_author_notes():
    w = World()

    for role in ("receptionist", "lab_staff", "provider_admin"):
        other = staff(role, w.provider_id, doctor_id=None)

        with pytest.raises(HTTPException) as exc_info:
            w.service.create_note(staff=other, patient_id=w.patient_id, data=w.note_request())

        assert exc_info.value.status_code == 403
        assert code_of(exc_info) == "NOTE_AUTHOR_REQUIRED"


def test_doctor_creates_draft_note_as_themselves():
    w = World()

    note = w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request())

    assert note.status == "draft"
    assert note.signed_at is None
    assert note.doctor_id == w.doctor.doctor_id          # author comes from the token
    assert note.encounter_id == w.encounter.id
    assert w.repo.session.commits == 1


def test_doctor_can_create_and_sign_in_one_step():
    w = World()

    note = w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request(sign=True))

    assert note.status == "signed"
    assert note.signed_at is not None


def test_unknown_encounter_is_404():
    w = World()

    with pytest.raises(HTTPException) as exc_info:
        w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request(encounter_id=uuid4()))

    assert exc_info.value.status_code == 404
    assert code_of(exc_info) == "ENCOUNTER_NOT_FOUND"


def test_encounter_of_another_patient_is_404():
    w = World()
    other_patient = uuid4()
    w.repo.profiles.add((other_patient, w.provider_id))

    with pytest.raises(HTTPException) as exc_info:
        w.service.create_note(staff=w.doctor, patient_id=other_patient, data=w.note_request())

    assert code_of(exc_info) == "ENCOUNTER_NOT_FOUND"


def test_doctor_cannot_write_on_another_doctors_visit():
    w = World()
    colleague = staff("doctor", w.provider_id)

    with pytest.raises(HTTPException) as exc_info:
        w.service.create_note(staff=colleague, patient_id=w.patient_id, data=w.note_request())

    assert exc_info.value.status_code == 403
    assert code_of(exc_info) == "NOTE_NOT_ALLOWED"


def test_visit_without_assigned_doctor_cannot_be_documented():
    w = World(with_encounter_doctor=False)

    with pytest.raises(HTTPException) as exc_info:
        w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request())

    assert code_of(exc_info) == "NOTE_NOT_ALLOWED"


def test_addendum_requires_a_signed_note_of_the_same_visit():
    w = World()
    draft = w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request())

    # correcting a draft is refused
    with pytest.raises(HTTPException) as exc_info:
        w.service.create_note(
            staff=w.doctor,
            patient_id=w.patient_id,
            data=w.note_request(note_type="addendum", addendum_to_note_id=draft.note_id),
        )

    assert exc_info.value.status_code == 409
    assert code_of(exc_info) == "NOTE_NOT_SIGNED"

    # correcting a note that does not exist is refused
    with pytest.raises(HTTPException) as exc_info:
        w.service.create_note(
            staff=w.doctor,
            patient_id=w.patient_id,
            data=w.note_request(note_type="addendum", addendum_to_note_id=uuid4()),
        )

    assert code_of(exc_info) == "NOTE_NOT_FOUND"

    # once signed, the addendum is accepted and points at the original
    w.service.sign_note(staff=w.doctor, patient_id=w.patient_id, note_id=draft.note_id)

    addendum = w.service.create_note(
        staff=w.doctor,
        patient_id=w.patient_id,
        data=w.note_request(note_type="addendum", addendum_to_note_id=draft.note_id, note_text="Correction."),
    )

    assert addendum.note_type == "addendum"
    assert addendum.addendum_to_note_id == draft.note_id


def test_integrity_error_becomes_409_and_rolls_back():
    from sqlalchemy.exc import IntegrityError

    w = World()

    def boom(note):
        raise IntegrityError("insert", {}, Exception("fk"))

    w.repo.add_note = boom

    with pytest.raises(HTTPException) as exc_info:
        w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request())

    assert exc_info.value.status_code == 409
    assert code_of(exc_info) == "NOTE_CONFLICT"
    assert w.repo.session.rollbacks == 1


# ============================================================
# SIGNING NOTES
# ============================================================
def test_only_the_author_can_sign():
    w = World()
    draft = w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request())
    colleague = staff("doctor", w.provider_id)

    with pytest.raises(HTTPException) as exc_info:
        w.service.sign_note(staff=colleague, patient_id=w.patient_id, note_id=draft.note_id)

    assert exc_info.value.status_code == 403
    assert code_of(exc_info) == "NOTE_NOT_ALLOWED"


def test_signing_twice_is_a_conflict():
    w = World()
    draft = w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request())

    signed = w.service.sign_note(staff=w.doctor, patient_id=w.patient_id, note_id=draft.note_id)
    assert signed.status == "signed"
    assert signed.signed_at is not None

    with pytest.raises(HTTPException) as exc_info:
        w.service.sign_note(staff=w.doctor, patient_id=w.patient_id, note_id=draft.note_id)

    assert exc_info.value.status_code == 409
    assert code_of(exc_info) == "NOTE_ALREADY_SIGNED"


def test_sign_unknown_note_is_404():
    w = World()

    with pytest.raises(HTTPException) as exc_info:
        w.service.sign_note(staff=w.doctor, patient_id=w.patient_id, note_id=uuid4())

    assert code_of(exc_info) == "NOTE_NOT_FOUND"


def test_notes_of_another_provider_are_invisible():
    w = World()
    note = w.service.create_note(staff=w.doctor, patient_id=w.patient_id, data=w.note_request(sign=True))

    stranger = staff("doctor", uuid4())
    w.repo.profiles.add((w.patient_id, stranger.provider_id))  # even if the patient is also registered there
    # ...and even if the stranger treats the patient at their own provider.
    w.repo.appointments.append(SimpleNamespace(
        provider_id=stranger.provider_id, patient_id=w.patient_id,
        doctor_id=stranger.doctor_id, status="confirmed",
    ))

    with pytest.raises(HTTPException) as exc_info:
        w.service.get_note(staff=stranger, patient_id=w.patient_id, note_id=note.note_id)

    assert code_of(exc_info) == "NOTE_NOT_FOUND"


# ============================================================
# TREATING-DOCTOR READ RULE
# ============================================================


def _reads(service, who, patient_id):
    """Every doctor-facing read; each must pass or fail together."""
    return [
        lambda: service.get_medical_history(staff=who, patient_id=patient_id),
        lambda: service.list_visits(staff=who, patient_id=patient_id, limit=10, offset=0),
        lambda: service.list_reports(staff=who, patient_id=patient_id, report_type=None, limit=10, offset=0),
        lambda: service.list_notes(staff=who, patient_id=patient_id, encounter_id=None, limit=10, offset=0),
    ]


def _assert_all_404(service, who, patient_id):
    for read in _reads(service, who, patient_id):
        with pytest.raises(HTTPException) as exc_info:
            read()
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "PATIENT_NOT_FOUND"


def _assert_all_allowed(service, who, patient_id):
    for read in _reads(service, who, patient_id):
        read()


def _no_encounters_world():
    w = World()
    w.repo.encounters.clear()
    return w


def _appointment(w, doctor_id, status):
    w.repo.appointments.append(
        SimpleNamespace(provider_id=w.provider_id, patient_id=w.patient_id, doctor_id=doctor_id, status=status)
    )


def test_doctor_with_encounter_can_read():
    w = World()
    _assert_all_allowed(w.service, w.doctor, w.patient_id)


def test_doctor_with_appointment_only_can_read():
    w = _no_encounters_world()
    _appointment(w, w.doctor.doctor_id, "confirmed")
    _assert_all_allowed(w.service, w.doctor, w.patient_id)


def test_doctor_without_any_relationship_gets_404():
    w = _no_encounters_world()
    _assert_all_404(w.service, w.doctor, w.patient_id)


@pytest.mark.parametrize("status", ["confirmed", "completed"])
def test_accepted_appointment_alone_grants_access(status):
    w = _no_encounters_world()
    _appointment(w, w.doctor.doctor_id, status)
    _assert_all_allowed(w.service, w.doctor, w.patient_id)


@pytest.mark.parametrize("status", ["pending", "cancelled", "no_show"])
def test_non_accepted_appointment_alone_does_not_grant_access(status):
    w = _no_encounters_world()
    _appointment(w, w.doctor.doctor_id, status)
    _assert_all_404(w.service, w.doctor, w.patient_id)


@pytest.mark.parametrize("status", ["pending", "cancelled", "no_show"])
def test_encounter_grants_access_whatever_the_appointment_status(status):
    w = World()
    _appointment(w, w.doctor.doctor_id, status)
    _assert_all_allowed(w.service, w.doctor, w.patient_id)


def test_qualifying_statuses_are_exactly_confirmed_and_completed():
    assert set(CARE_RELATIONSHIP_APPOINTMENT_STATUSES) == {"confirmed", "completed"}


def test_another_doctors_patient_is_404():
    w = World()
    _appointment(w, w.doctor.doctor_id, "confirmed")
    colleague = staff("doctor", w.provider_id)
    _assert_all_404(w.service, colleague, w.patient_id)


def test_relationship_at_another_provider_does_not_grant_access():
    w = World()
    other = staff("doctor", uuid4(), doctor_id=w.doctor.doctor_id)
    w.repo.profiles.add((w.patient_id, other.provider_id))  # patient registered at both providers
    _assert_all_404(w.service, other, w.patient_id)
    assert all(call == other.provider_id for call in w.repo.calls)


def test_report_details_follow_the_rule():
    w = _no_encounters_world()
    for read in (
        lambda: w.service.get_lab_report(staff=w.doctor, patient_id=w.patient_id, report_id=uuid4()),
        lambda: w.service.get_radiology_report(staff=w.doctor, patient_id=w.patient_id, report_id=uuid4()),
        lambda: w.service.get_note(staff=w.doctor, patient_id=w.patient_id, note_id=uuid4()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            read()
        assert exc_info.value.detail["code"] == "PATIENT_NOT_FOUND"


def test_lab_staff_report_access_is_unchanged():
    w = _no_encounters_world()
    w.service.list_reports(staff=staff("lab_staff", w.provider_id, doctor_id=None), patient_id=w.patient_id,
                           report_type=None, limit=10, offset=0)


def test_repository_relationship_query_is_provider_scoped():
    from sqlalchemy.dialects import mssql

    from app.repositories.ehr_record_repository import EHRRecordRepository

    class Capture:
        statement = None

        def scalar(self, statement):
            Capture.statement = statement
            return False

    provider_id, patient_id, doctor_id = uuid4(), uuid4(), uuid4()
    assert EHRRecordRepository(Capture()).doctor_has_care_relationship(
        provider_id=provider_id, patient_id=patient_id, doctor_id=doctor_id
    ) is False
    sql = str(Capture.statement.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))
    assert sql.count(f"'{provider_id}'") == 2
    assert sql.count(f"'{doctor_id}'") == 2
    assert "ehr_encounters" in sql and "appointments" in sql
    assert "appointments.status IN ('confirmed', 'completed')" in sql
