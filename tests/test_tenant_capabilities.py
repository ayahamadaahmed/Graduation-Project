import pytest

from agent.medmind.tenancy.capabilities import (
    Capability,
    ProviderType,
    build_tenant_capabilities,
    resolve_provider_type,
)


def test_clinic_gets_appointment_capabilities():
    tenant = build_tenant_capabilities(
        tenant_id="clinic-001",
        provider_type=ProviderType.CLINIC,
    )

    assert tenant.allows(
        Capability.APPOINTMENT_BOOK
    )

    assert tenant.allows(
        Capability.DOCTOR_SEARCH
    )

    assert not tenant.allows(
        Capability.LAB_RESULT_LOOKUP
    )


def test_hospital_gets_appointment_and_lab_capabilities():
    tenant = build_tenant_capabilities(
        tenant_id="hospital-001",
        provider_type=ProviderType.HOSPITAL,
    )

    assert tenant.allows(
        Capability.APPOINTMENT_BOOK
    )

    assert tenant.allows(
        Capability.DEPARTMENT_SEARCH
    )

    assert tenant.allows(
        Capability.LAB_RESULT_LOOKUP
    )

    assert tenant.allows(
        Capability.LAB_RESULT_EXPLANATION
    )


def test_lab_gets_lab_capabilities():
    tenant = build_tenant_capabilities(
        tenant_id="lab-001",
        provider_type=ProviderType.LAB,
    )

    assert tenant.allows(
        Capability.LAB_TEST_CATALOG
    )

    assert tenant.allows(
        Capability.LAB_TEST_PREPARATION
    )

    assert tenant.allows(
        Capability.LAB_RESULT_LOOKUP
    )


def test_tenant_can_disable_default_capability():
    tenant = build_tenant_capabilities(
        tenant_id="clinic-no-voice-booking",
        provider_type=ProviderType.CLINIC,
        disable=[
            Capability.APPOINTMENT_BOOK,
        ],
    )

    assert not tenant.allows(
        Capability.APPOINTMENT_BOOK
    )

    assert tenant.allows(
        Capability.DOCTOR_SEARCH
    )


def test_tenant_can_enable_extra_capability():
    tenant = build_tenant_capabilities(
        tenant_id="clinic-with-labs",
        provider_type=ProviderType.CLINIC,
        enable=[
            Capability.LAB_RESULT_LOOKUP,
        ],
    )

    assert tenant.allows(
        Capability.LAB_RESULT_LOOKUP
    )


def test_unknown_capability_fails_closed():
    tenant = build_tenant_capabilities(
        tenant_id="hospital-001",
        provider_type=ProviderType.HOSPITAL,
    )

    assert not tenant.allows(
        "something.not.real"
    )


def test_invalid_configuration_fails_fast():
    with pytest.raises(ValueError):
        build_tenant_capabilities(
            tenant_id="clinic-001",
            provider_type=ProviderType.CLINIC,
            enable=[
                "unknown.capability",
            ],
        )


def test_empty_tenant_id_is_rejected():
    with pytest.raises(ValueError):
        build_tenant_capabilities(
            tenant_id="   ",
            provider_type=ProviderType.CLINIC,
        )

def test_diagnostic_lab_org_type_maps_to_lab():
    assert (
        resolve_provider_type(
            "diagnostic_lab"
        )
        == ProviderType.LAB
    )


def test_database_lab_provider_gets_lab_capabilities():
    tenant = build_tenant_capabilities(
        tenant_id="lab-001",
        provider_type="diagnostic_lab",
    )

    assert tenant.provider_type == ProviderType.LAB

    assert tenant.allows(
        Capability.LAB_RESULT_LOOKUP
    )

    assert tenant.allows(
        Capability.LAB_RESULT_EXPLANATION
    )


def test_unsupported_pharmacy_fails_closed():
    with pytest.raises(
        ValueError,
        match="Unsupported provider org_type",
    ):
        build_tenant_capabilities(
            tenant_id="pharmacy-001",
            provider_type="pharmacy",
        )        