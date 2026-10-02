import asyncio

from medmind.service import (
    MedMindService,
)

from app.services.medmind_registry import (
    MedMindServiceRegistry,
)

from uuid import uuid4

import pytest

from medmind.tenancy.capabilities import (
    ProviderType,
    build_tenant_capabilities,
)
from medmind.tenancy.context import (
    TenantContext,
)


def make_tenant_context(
    tenant_id: str,
) -> TenantContext:

    return TenantContext(
        tenant_id=tenant_id,
        provider_id=uuid4(),
        provider_name="Test Clinic",
        capabilities=build_tenant_capabilities(
            tenant_id=tenant_id,
            provider_type=ProviderType.CLINIC,
        ),
    )
class FakeResources:

    def __init__(
        self,
    ):
        self.close_calls = 0

    async def aclose(
        self,
    ):
        self.close_calls += 1


class FakeService:

    def __init__(
        self,
    ):
        self.close_calls = 0

    async def close(
        self,
    ):
        self.close_calls += 1


def test_service_close_closes_resources_once():

    resources = FakeResources()

    service = MedMindService(
        tenant_id="clinic-001",
        agent=object(),
        nlu=object(),
        understanding=object(),
        booking_workflow=object(),
        cancel_workflow=object(),
        reschedule_workflow=object(),
        state_store=object(),
        memory=object(),
        tools=object(),
        mcp_resources=resources,
    )

    asyncio.run(
        service.close()
    )

    asyncio.run(
        service.close()
    )

    assert (
        resources.close_calls
        == 1
    )

    assert (
        service._closed
        is True
    )


def test_registry_close_closes_all_services():

    first_service = (
        FakeService()
    )

    second_service = (
        FakeService()
    )

    registry = (
        MedMindServiceRegistry()
    )

    registry._services = {
        "clinic-001":
            first_service,

        "hospital-001":
            second_service,
    }

    asyncio.run(
        registry.close()
    )

    assert (
        first_service.close_calls
        == 1
    )

    assert (
        second_service.close_calls
        == 1
    )

    assert (
        registry._services
        == {}
    )

def test_service_keeps_tenant_context():
    context = make_tenant_context(
        "clinic-001"
    )

    service = MedMindService(
        tenant_id="clinic-001",
        agent=object(),
        nlu=object(),
        understanding=object(),
        booking_workflow=object(),
        cancel_workflow=object(),
        reschedule_workflow=object(),
        state_store=object(),
        memory=object(),
        tools=object(),
        tenant_context=context,
    )

    assert (
        service.tenant_context
        is context
    )

    assert (
        service.tenant_id
        == "clinic-001"
    )


def test_service_rejects_mismatched_tenant_context():
    context = make_tenant_context(
        "hospital-001"
    )

    with pytest.raises(
        ValueError,
        match="tenant_context tenant_id",
    ):
        MedMindService(
            tenant_id="clinic-001",
            agent=object(),
            nlu=object(),
            understanding=object(),
            booking_workflow=object(),
            cancel_workflow=object(),
            reschedule_workflow=object(),
            state_store=object(),
            memory=object(),
            tools=object(),
            tenant_context=context,
        )    