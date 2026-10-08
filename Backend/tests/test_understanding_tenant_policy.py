from __future__ import annotations

from uuid import uuid4

from medmind.tenancy.capabilities import (
    ProviderType,
    build_tenant_capabilities,
)
from medmind.tenancy.context import (
    TenantContext,
)
from medmind.understanding.capabilities import (
    CAPABILITIES,
)
from medmind.understanding.tenant_policy import (
    UNDERSTANDING_CAPABILITY_REQUIREMENTS,
    allowed_understanding_capabilities,
)


def make_context(
    *,
    tenant_id: str,
    provider_type: ProviderType,
) -> TenantContext:

    return TenantContext(
        tenant_id=tenant_id,
        provider_id=uuid4(),
        provider_name="Test Provider",
        capabilities=(
            build_tenant_capabilities(
                tenant_id=tenant_id,
                provider_type=provider_type,
            )
        ),
    )


def test_every_understanding_capability_has_tenant_policy():

    registered = {
        capability.name
        for capability in CAPABILITIES
    }

    mapped = set(
        UNDERSTANDING_CAPABILITY_REQUIREMENTS
    )

    assert mapped == registered


def test_legacy_mode_does_not_filter():

    assert (
        allowed_understanding_capabilities(
            None
        )
        is None
    )


def test_clinic_allows_doctor_capability():

    context = make_context(
        tenant_id="clinic-001",
        provider_type=ProviderType.CLINIC,
    )

    allowed = (
        allowed_understanding_capabilities(
            context
        )
    )

    assert allowed is not None

    assert (
        "provider.search_doctors"
        in allowed
    )

    assert (
        "appointment.create"
        in allowed
    )

    assert (
        "provider.get_slots"
        in allowed
    )


def test_lab_does_not_allow_doctor_discovery():

    context = make_context(
        tenant_id="lab-001",
        provider_type=ProviderType.LAB,
    )

    allowed = (
        allowed_understanding_capabilities(
            context
        )
    )

    assert allowed is not None

    assert (
        "provider.search_doctors"
        not in allowed
    )

    assert (
        "provider.get_services"
        in allowed
    )

    assert (
        "provider.get_slots"
        in allowed
    )


def test_hospital_allows_doctor_discovery():

    context = make_context(
        tenant_id="hospital-001",
        provider_type=ProviderType.HOSPITAL,
    )

    allowed = (
        allowed_understanding_capabilities(
            context
        )
    )

    assert allowed is not None

    assert (
        "provider.search_doctors"
        in allowed
    )