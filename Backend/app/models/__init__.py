"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.provider import (
    Provider,
)
from app.models.branch import (
    Branch,
)
from app.models.specialty import (
    Specialty,
)
from app.models.department import (
    Department,
    DepartmentSpecialty,
)
from app.models.service import (
    Service,
    ServiceSpecialty,
)
from app.models.doctor import (
    Doctor,
    DoctorBranch,
    DoctorService,
    DoctorVerificationDecision,
)
from app.models.scheduling import (
    DoctorWorkingHour,
    DoctorScheduleException,
    DoctorAvailabilitySlot,
)
from app.models.patient import (
    Patient,
)
from app.models.patient_provider_profile import (
    PatientProviderProfile,
)
from app.models.patient_branch_profile import (
    PatientBranchProfile,
)
from app.models.sequences import (
    BranchMRNSequence,
    PatientNumberSequence,
)
from app.models.appointment import (
    Appointment,
    AppointmentStatusHistory,
)
from app.models.reminder import (
    Reminder,
)
from app.models.auth import (
    UserAccount,
    ProviderMembership,
)
from app.models.staff_audit_log import (
    StaffAuditLog,
)
from app.models.idempotency import (
    IdempotencyRequest,
)
from app.models.ehr_encounter import (
    EHREncounter,
)
from app.models.diagnostic_attachment import (
    DiagnosticAttachment,
)
from app.models.lab_report import (
    LabReport,
)
from app.models.lab_result import (
    LabResult,
)
from app.models.radiology_report import (
    RadiologyReport,
)
from app.models.diagnostic_assessment import (
    DiagnosticAssessment,
)

from app.models.patient_condition import (
    PatientCondition,
)
from app.models.patient_allergy import (
    PatientAllergy,
)
from app.models.patient_medication import (
    PatientMedication,
)
from app.models.clinical_note import (
    ClinicalNote,
)
from app.models.patient_access_grant import (
    PatientAccessGrant,
)

__all__ = [
    "Provider",
    "Branch",
    "Specialty",
    "Department",
    "DepartmentSpecialty",
    "Service",
    "ServiceSpecialty",
    "Doctor",
    "DoctorBranch",
    "DoctorService",
    "DoctorVerificationDecision",
    "DoctorWorkingHour",
    "DoctorScheduleException",
    "DoctorAvailabilitySlot",
    "Patient",
    "PatientProviderProfile",
    "PatientBranchProfile",
    "BranchMRNSequence",
    "PatientNumberSequence",
    "Appointment",
    "AppointmentStatusHistory",
    "Reminder",
    "UserAccount",
    "ProviderMembership",
    "StaffAuditLog",
    "IdempotencyRequest",
    "EHREncounter",
    "DiagnosticAttachment",
    "LabReport",
    "LabResult",
    "RadiologyReport",
    "DiagnosticAssessment",
    "PatientCondition",
    "PatientAllergy",
    "PatientMedication",
    "ClinicalNote",
    "PatientAccessGrant",
]
