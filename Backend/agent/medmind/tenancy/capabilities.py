from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ProviderType(str, Enum):
    CLINIC = "clinic"
    HOSPITAL = "hospital"
    LAB = "lab"


_PROVIDER_TYPE_ALIASES: dict[str, ProviderType] = {
    "clinic": ProviderType.CLINIC,
    "hospital": ProviderType.HOSPITAL,

    # Current DB value for laboratory providers.
    "diagnostic_lab": ProviderType.LAB,

    # Accepted canonical aliases for future data.
    "lab": ProviderType.LAB,
    "laboratory": ProviderType.LAB,
}


def resolve_provider_type(
    org_type: ProviderType | str,
) -> ProviderType:
    """
    Convert the provider.org_type stored in the database
    into MedMind's canonical provider type.

    Unknown provider types fail closed.
    """

    if isinstance(
        org_type,
        ProviderType,
    ):
        return org_type

    normalized = (
        org_type
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    provider_type = (
        _PROVIDER_TYPE_ALIASES.get(
            normalized
        )
    )

    if provider_type is None:
        raise ValueError(
            "Unsupported provider org_type: "
            f"{org_type!r}"
        )

    return provider_type

class Capability(str, Enum):
    # ============================================================
    # Appointment domain
    # ============================================================

    APPOINTMENT_BOOK = "appointment.book"
    APPOINTMENT_GET = "appointment.get"
    APPOINTMENT_CANCEL = "appointment.cancel"
    APPOINTMENT_RESCHEDULE = "appointment.reschedule"
    APPOINTMENT_CONFIRM = "appointment.confirm"
    APPOINTMENT_AVAILABLE_SLOTS = "appointment.available_slots"

    # ============================================================
    # Provider catalog
    # ============================================================

    SPECIALTY_SEARCH = "catalog.specialty.search"
    DOCTOR_SEARCH = "catalog.doctor.search"
    SERVICE_SEARCH = "catalog.service.search"
    DEPARTMENT_SEARCH = "catalog.department.search"

    # ============================================================
    # Provider information
    # ============================================================

    WORKING_HOURS = "provider.working_hours"
    PROVIDER_INFO = "provider.info"
    PROVIDER_POLICY = "provider.policy"

    # ============================================================
    # Knowledge
    # ============================================================

    KNOWLEDGE_SEARCH = "knowledge.search"

    # ============================================================
    # Patient domain
    # ============================================================

    PATIENT_IDENTITY = "patient.identity"
    PATIENT_PROFILE = "patient.profile"

    # ============================================================
    # Laboratory domain
    # ============================================================

    LAB_TEST_CATALOG = "lab.test_catalog"
    LAB_TEST_PREPARATION = "lab.test_preparation"
    LAB_RESULT_LOOKUP = "lab.result_lookup"
    LAB_RESULT_EXPLANATION = "lab.result_explanation"

    # ============================================================
    # Support
    # ============================================================

    HUMAN_SUPPORT = "support.human"


COMMON_CAPABILITIES = frozenset(
    {
        Capability.PROVIDER_INFO,
        Capability.PROVIDER_POLICY,
        Capability.WORKING_HOURS,
        Capability.KNOWLEDGE_SEARCH,
        Capability.HUMAN_SUPPORT,
    }
)


APPOINTMENT_CAPABILITIES = frozenset(
    {
        Capability.APPOINTMENT_BOOK,
        Capability.APPOINTMENT_GET,
        Capability.APPOINTMENT_CANCEL,
        Capability.APPOINTMENT_RESCHEDULE,
        Capability.APPOINTMENT_CONFIRM,
        Capability.APPOINTMENT_AVAILABLE_SLOTS,
        Capability.PATIENT_IDENTITY,
    }
)


DEFAULT_CAPABILITIES: dict[
    ProviderType,
    frozenset[Capability],
] = {
    ProviderType.CLINIC: (
        COMMON_CAPABILITIES
        | APPOINTMENT_CAPABILITIES
        | frozenset(
            {
                Capability.SPECIALTY_SEARCH,
                Capability.DOCTOR_SEARCH,
                Capability.SERVICE_SEARCH,
            }
        )
    ),

    ProviderType.HOSPITAL: (
        COMMON_CAPABILITIES
        | APPOINTMENT_CAPABILITIES
        | frozenset(
            {
                Capability.SPECIALTY_SEARCH,
                Capability.DOCTOR_SEARCH,
                Capability.SERVICE_SEARCH,
                Capability.DEPARTMENT_SEARCH,
                Capability.PATIENT_PROFILE,
                Capability.LAB_RESULT_LOOKUP,
                Capability.LAB_RESULT_EXPLANATION,
            }
        )
    ),

    ProviderType.LAB: (
        COMMON_CAPABILITIES
        | APPOINTMENT_CAPABILITIES
        | frozenset(
            {
                Capability.SERVICE_SEARCH,
                Capability.LAB_TEST_CATALOG,
                Capability.LAB_TEST_PREPARATION,
                Capability.LAB_RESULT_LOOKUP,
                Capability.LAB_RESULT_EXPLANATION,
            }
        )
    ),
}


@dataclass(
    frozen=True,
    slots=True,
)
class TenantCapabilitySet:
    """
    Effective capabilities for one tenant.

    This object contains authorization/routing policy only.

    It must not contain provider business data such as:
    doctors, services, branches, lab results, or appointments.
    """

    tenant_id: str
    provider_type: ProviderType
    enabled: frozenset[Capability]

    def allows(
        self,
        capability: Capability | str,
    ) -> bool:
        """
        Fail closed.

        Unknown capability names are never considered enabled.
        """

        try:
            normalized = (
                capability
                if isinstance(capability, Capability)
                else Capability(capability)
            )
        except ValueError:
            return False

        return normalized in self.enabled


def build_tenant_capabilities(
    *,
    tenant_id: str,
    provider_type: ProviderType | str,
    enable: Iterable[Capability | str] = (),
    disable: Iterable[Capability | str] = (),
) -> TenantCapabilitySet:
    """
    Build the effective capability set for a tenant.

    Defaults come from provider type.

    Individual tenants may then:
    - enable additional capabilities
    - disable capabilities they don't use

    Invalid configuration fails immediately rather than silently
    enabling/disabling the wrong feature.
    """

    normalized_tenant_id = tenant_id.strip()

    if not normalized_tenant_id:
        raise ValueError(
            "tenant_id must not be empty"
        )

    normalized_provider_type = (
    resolve_provider_type(
        provider_type
    )
)

    capabilities = set(
        DEFAULT_CAPABILITIES[
            normalized_provider_type
        ]
    )

    capabilities.update(
        _coerce_capabilities(enable)
    )

    capabilities.difference_update(
        _coerce_capabilities(disable)
    )

    return TenantCapabilitySet(
        tenant_id=normalized_tenant_id,
        provider_type=normalized_provider_type,
        enabled=frozenset(capabilities),
    )


def _coerce_capabilities(
    values: Iterable[Capability | str],
) -> set[Capability]:

    result: set[Capability] = set()

    for value in values:
        capability = (
            value
            if isinstance(value, Capability)
            else Capability(value)
        )

        result.add(capability)

    return result