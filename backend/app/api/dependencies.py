from typing import Annotated


from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.services.idempotency_service import (
    idempotency_service,
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

from app.repositories.patient_branch_profile_repository import (
    PatientBranchProfileRepository,
)

from app.services.patient_branch_profile_service import (
    PatientBranchProfileService,
)

from app.core.config import get_settings
from app.integrations.telegram.client import (
    TelegramClient,
)

DatabaseSession = Annotated[Session, Depends(get_db_session)]



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
def get_telegram_client() -> TelegramClient:
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN "
            "is not configured."
        )

    return TelegramClient(
        bot_token=(
            settings.telegram_bot_token
        )
    )


TelegramClientDependency = Annotated[
    TelegramClient,
    Depends(get_telegram_client),
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
    provider = service.get_provider(tenant_key.strip())

    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PROVIDER_NOT_FOUND",
                "message": "No active provider matches X-Tenant-ID.",
            },
        )

    return provider


CurrentProvider = Annotated[
    Provider,
    Depends(get_current_provider),
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