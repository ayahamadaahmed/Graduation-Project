from dataclasses import dataclass
from uuid import uuid4

import pytest

from agent.medmind.tenancy.capabilities import (
    Capability,
    ProviderType,
)
from agent.medmind.tenancy.factory import (
    build_tenant_context,
)


@dataclass
class FakeProvider:
    id: object
    tenant_key: str
    name: str
    org_type: str
    timezone: str = "Africa/Cairo"

def test_clinic_provider_builds_clinic_context():
    provider = FakeProvider(
        id=uuid4(),
        tenant_key="clinic-001",
        name="Test Clinic",
        org_type="clinic",
    )

    context = build_tenant_context(
        provider
    )
    
    assert context.timezone == "Africa/Cairo"
    assert context.tenant_id == "clinic-001"

    assert (
        context.capabilities.provider_type
        == ProviderType.CLINIC
    )

    assert context.allows(
        Capability.APPOINTMENT_BOOK
    )

    assert not context.allows(
        Capability.LAB_RESULT_LOOKUP
    )


def test_diagnostic_lab_builds_lab_context():
    provider = FakeProvider(
        id=uuid4(),
        tenant_key="lab-001",
        name="Test Lab",
        org_type="diagnostic_lab",
    )

    context = build_tenant_context(
        provider
    )

    assert (
        context.provider_type
        == "lab"
    )

    assert context.allows(
        Capability.LAB_TEST_CATALOG
    )

    assert context.allows(
        Capability.LAB_RESULT_LOOKUP
    )


def test_hospital_builds_hospital_context():
    provider = FakeProvider(
        id=uuid4(),
        tenant_key="hospital-001",
        name="Test Hospital",
        org_type="hospital",
    )

    context = build_tenant_context(
        provider
    )

    assert context.allows(
        Capability.APPOINTMENT_BOOK
    )

    assert context.allows(
        Capability.DEPARTMENT_SEARCH
    )

    assert context.allows(
        Capability.LAB_RESULT_LOOKUP
    )


def test_unsupported_provider_type_fails_closed():
    provider = FakeProvider(
        id=uuid4(),
        tenant_key="pharmacy-001",
        name="Test Pharmacy",
        org_type="pharmacy",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported provider org_type",
    ):
        build_tenant_context(
            provider
        )