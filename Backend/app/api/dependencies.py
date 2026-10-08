from typing import Annotated


from fastapi import (
    Depends,
    Header,
    HTTPException,
    status,
)
from app.repositories.ehr_encounter_repository import (
    EHREncounterRepository,
)

from app.services.diagnostic_attachment_binding_service import (
    DiagnosticAttachmentBindingService,
)
from app.repositories.staff_audit_repository import (
    StaffAuditRepository,
)
from app.services.staff_audit_service import (
    StaffAuditService,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.security.staff_context import (
    StaffContext,
)
from app.security.tokens import (
    TokenError,
    decode_access_token,
)
from sqlalchemy.orm import Session

from app.repositories.auth_repository import (
    AuthRepository,
)
from app.services.staff_access_service import (
    StaffAccessService,
)

from app.services.idempotency_service import (
    idempotency_service,
)
from app.repositories.diagnostic_attachment_repository import (
    DiagnosticAttachmentRepository,
)
from app.repositories.radiology_repository import (
    RadiologyRepository,
)

from app.services.radiology_persistence_service import (
    RadiologyPersistenceService,
)

from app.services.radiology_persistence_adapter import (
    RadiologyPersistenceAdapter,
)
from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentService,
)
from app.db.session import get_db_session
from app.models import Provider
from app.repositories.catalog_repository import CatalogRepository
from app.services.catalog_service import CatalogService
from app.repositories.working_hours_repository import (
    WorkingHoursRepository,
)
from app.services.working_hours_service import (
    WorkingHoursService,
)

from app.core.patient_identity import (
    PatientIdentityProtector,
)
from app.repositories.patient_repository import (
    PatientRepository,
)
from app.services.patient_service import (
    PatientService,
)

from app.repositories.appointment_repository import (
    AppointmentRepository,
)
from app.services.appointment_service import (
    AppointmentService,
)

from app.repositories.lab_repository import (
    LabRepository,
)

from app.services.lab_persistence_service import (
    LabPersistenceService,
)

from app.services.pathology_persistence_adapter import (
    PathologyPersistenceAdapter,
)

from app.repositories.patient_branch_profile_repository import (
    PatientBranchProfileRepository,
)

from app.services.patient_branch_profile_service import (
    PatientBranchProfileService,
)
import logging
import time
from app.core.config import get_settings

logger = logging.getLogger(
    "uvicorn.error"
)

DatabaseSession = Annotated[Session, Depends(get_db_session)]


def get_staff_access_service(
    session: DatabaseSession,
) -> StaffAccessService:

    repository = AuthRepository(
        session
    )

    return StaffAccessService(
        repository
    )


StaffAccessServiceDependency = Annotated[
    StaffAccessService,
    Depends(
        get_staff_access_service
    ),
]

def get_working_hours_service(
    session: DatabaseSession,
) -> WorkingHoursService:
    repository = WorkingHoursRepository(session)

    return WorkingHoursService(repository)


WorkingHoursServiceDependency = Annotated[
    WorkingHoursService,
    Depends(get_working_hours_service),
]

def get_catalog_service(
    session: DatabaseSession,
) -> CatalogService:
    return CatalogService(CatalogRepository(session))


CatalogServiceDependency = Annotated[
    CatalogService,
    Depends(get_catalog_service),
]


def get_current_provider(
    service: CatalogServiceDependency,
    tenant_key: Annotated[
        str,
        Header(
            alias="X-Tenant-ID",
            min_length=1,
            max_length=100,
        ),
    ],
) -> Provider:

    started_at = (
        time.perf_counter()
    )

    provider = (
        service.get_provider(
            tenant_key.strip()
        )
    )

    lookup_ms = (
        (
            time.perf_counter()
            - started_at
        )
        * 1000
    )

    logger.info(
        "current_provider_timing "
        "lookup_ms=%.2f "
        "found=%s",
        lookup_ms,
        provider is not None,
    )

    if provider is None:

        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail={
                "code":
                    "PROVIDER_NOT_FOUND",

                "message":
                    (
                        "No active provider "
                        "matches X-Tenant-ID."
                    ),
            },
        )

    return provider

CurrentProvider = Annotated[
    Provider,
    Depends(get_current_provider),
]

staff_bearer_scheme = HTTPBearer(
    auto_error=False
)

def get_current_staff(
    provider: CurrentProvider,
    service: StaffAccessServiceDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(staff_bearer_scheme),
    ],
) -> StaffContext:

    # ========================================================
    # 1. Bearer token required
    # ========================================================

    if credentials is None:

        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail={
                "code":
                    "STAFF_AUTH_REQUIRED",

                "message": (
                    "A valid staff access token "
                    "is required."
                ),
            },
            headers={
                "WWW-Authenticate":
                    "Bearer",
            },
        )

    # ========================================================
    # 2. Verify JWT signature / expiry / claims
    # ========================================================

    try:

        claims = decode_access_token(
            credentials.credentials
        )

    except TokenError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail={
                "code":
                    "INVALID_ACCESS_TOKEN",

                "message": (
                    "The staff access token "
                    "is invalid or expired."
                ),
            },
            headers={
                "WWW-Authenticate":
                    "Bearer",
            },
        ) from exc

    # ========================================================
    # 3. Revalidate account + membership against DB
    # ========================================================

    user, membership = (
        service.resolve_current_staff(
            provider_id=provider.id,
            user_id=claims.user_id,
            membership_id=(
                claims.membership_id
            ),
            token_provider_id=(
                claims.provider_id
            ),
        )
    )

    # ========================================================
    # 4. Build trusted request context
    # ========================================================

    return StaffContext(
        user_id=user.id,
        membership_id=membership.id,
        provider_id=provider.id,
        role=membership.role,
        doctor_id=membership.doctor_id,
    )

CurrentStaff = Annotated[
    StaffContext,
    Depends(get_current_staff),
]

def get_patient_identity_protector(
) -> PatientIdentityProtector:
    settings = get_settings()

    if settings.national_id_hash_key is None:
        raise RuntimeError(
            "NATIONAL_ID_HASH_KEY is not configured."
        )

    if (
        settings.national_id_encryption_key
        is None
    ):
        raise RuntimeError(
            "NATIONAL_ID_ENCRYPTION_KEY "
            "is not configured."
        )

    return PatientIdentityProtector(
        hash_key=(
            settings
            .national_id_hash_key
            .get_secret_value()
        ),
        encryption_key=(
            settings
            .national_id_encryption_key
            .get_secret_value()
        ),
    )


def get_patient_service(
    session: DatabaseSession,
) -> PatientService:
    repository = PatientRepository(session)

    protector = (
        get_patient_identity_protector()
    )

    return PatientService(
        repository=repository,
        identity_protector=protector,
    )


PatientServiceDependency = Annotated[
    PatientService,
    Depends(get_patient_service),
]

def get_diagnostic_attachment_service(
    session: DatabaseSession,
) -> DiagnosticAttachmentService:

    settings = get_settings()

    repository = (
        DiagnosticAttachmentRepository(
            session
        )
    )

    return DiagnosticAttachmentService(
        repository=repository,
        storage_dir=(
            settings
            .diagnostic_storage_dir
        ),
        max_upload_bytes=(
            settings
            .diagnostic_max_upload_bytes
        ),
    )


DiagnosticAttachmentServiceDependency = Annotated[
    DiagnosticAttachmentService,
    Depends(
        get_diagnostic_attachment_service
    ),
]

def get_diagnostic_attachment_binding_service(
    session: DatabaseSession,
) -> DiagnosticAttachmentBindingService:

    patient_repository = PatientRepository(
        session
    )

    encounter_repository = (
        EHREncounterRepository(
            session
        )
    )

    return DiagnosticAttachmentBindingService(
        patient_repository=(
            patient_repository
        ),
        encounter_repository=(
            encounter_repository
        ),
    )


DiagnosticAttachmentBindingServiceDependency = Annotated[
    DiagnosticAttachmentBindingService,
    Depends(
        get_diagnostic_attachment_binding_service
    ),
]

def get_lab_persistence_service(
    session: DatabaseSession,
) -> LabPersistenceService:

    repository = LabRepository(
        session
    )

    return LabPersistenceService(
        repository
    )


LabPersistenceServiceDependency = Annotated[
    LabPersistenceService,
    Depends(
        get_lab_persistence_service
    ),
]


def get_pathology_persistence_adapter(
    attachment_service:
        DiagnosticAttachmentServiceDependency,
    lab_persistence_service:
        LabPersistenceServiceDependency,
) -> PathologyPersistenceAdapter:

    return PathologyPersistenceAdapter(
        attachment_service=(
            attachment_service
        ),
        lab_persistence_service=(
            lab_persistence_service
        ),
    )


PathologyPersistenceAdapterDependency = Annotated[
    PathologyPersistenceAdapter,
    Depends(
        get_pathology_persistence_adapter
    ),
]

def get_radiology_persistence_service(
    session: DatabaseSession,
) -> RadiologyPersistenceService:

    repository = RadiologyRepository(
        session
    )

    return RadiologyPersistenceService(
        repository
    )


RadiologyPersistenceServiceDependency = Annotated[
    RadiologyPersistenceService,
    Depends(
        get_radiology_persistence_service
    ),
]


def get_radiology_persistence_adapter(
    attachment_service:
        DiagnosticAttachmentServiceDependency,
    radiology_persistence_service:
        RadiologyPersistenceServiceDependency,
) -> RadiologyPersistenceAdapter:

    return RadiologyPersistenceAdapter(
        attachment_service=(
            attachment_service
        ),
        radiology_persistence_service=(
            radiology_persistence_service
        ),
    )


RadiologyPersistenceAdapterDependency = Annotated[
    RadiologyPersistenceAdapter,
    Depends(
        get_radiology_persistence_adapter
    ),
]

def get_appointment_service(
    session: DatabaseSession,
) -> AppointmentService:

    appointment_repository = (
        AppointmentRepository(
            session
        )
    )

    patient_repository = (
        PatientRepository(
            session
        )
    )

    branch_profile_repository = (
        PatientBranchProfileRepository(
            session
        )
    )

    branch_profile_service = (
        PatientBranchProfileService(
            branch_profile_repository
        )
    )

    identity_protector = (
        get_patient_identity_protector()
    )

    return AppointmentService(
        repository=(
            appointment_repository
        ),

        patient_repository=(
            patient_repository
        ),

        identity_protector=(
            identity_protector
        ),

        branch_profile_service=(
            branch_profile_service
        ),

        idempotency_service=(
            idempotency_service
        ),
    )


AppointmentServiceDependency = Annotated[
    AppointmentService,
    Depends(get_appointment_service),
]


def get_staff_audit_service(
    session: DatabaseSession,
) -> StaffAuditService:

    repository = StaffAuditRepository(
        session
    )

    return StaffAuditService(
        repository
    )


StaffAuditServiceDependency = Annotated[
    StaffAuditService,
    Depends(get_staff_audit_service),
]