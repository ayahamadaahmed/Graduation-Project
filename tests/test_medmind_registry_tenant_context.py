from uuid import uuid4
import asyncio
import pytest

from app.services.medmind_registry import (
    MedMindServiceRegistry,
)
from medmind.tenancy.capabilities import (
    ProviderType,
    build_tenant_capabilities,
)
from medmind.tenancy.context import (
    TenantContext,
)


def make_context(
    tenant_id: str,
    *,
    provider_id=None,
    provider_type: ProviderType = ProviderType.CLINIC,
) -> TenantContext:

    provider_id = (
        provider_id
        or uuid4()
    )

    return TenantContext(
        tenant_id=tenant_id,
        provider_id=provider_id,
        provider_name="Test Provider",
        capabilities=build_tenant_capabilities(
            tenant_id=tenant_id,
            provider_type=provider_type,
        ),
    )


class FakeService:

    def __init__(
        self,
        *,
        tenant_context,
    ):
        self.tenant_context = tenant_context


@pytest.mark.asyncio
async def test_registry_reuses_service_for_same_context(
    monkeypatch,
):
    context = make_context(
        "clinic-001"
    )

    created = []

    async def fake_create(
        **kwargs,
    ):
        service = FakeService(
            tenant_context=(
                kwargs["tenant_context"]
            ),
        )

        created.append(service)

        return service

    monkeypatch.setattr(
        "app.services.medmind_registry."
        "MedMindService.create",
        fake_create,
    )

    registry = MedMindServiceRegistry()

    first = await registry.get(
        tenant_id="clinic-001",
        tenant_context=context,
    )

    second = await registry.get(
        tenant_id="clinic-001",
        tenant_context=context,
    )

    assert first is second
    assert len(created) == 1


@pytest.mark.asyncio
async def test_registry_rejects_requested_context_for_wrong_tenant():
    registry = MedMindServiceRegistry()

    context = make_context(
        "hospital-001",
        provider_type=ProviderType.HOSPITAL,
    )

    with pytest.raises(
        ValueError,
        match="tenant_context tenant_id",
    ):
        await registry.get(
            tenant_id="clinic-001",
            tenant_context=context,
        )


@pytest.mark.asyncio
async def test_registry_rejects_legacy_cached_service_for_production_context():
    registry = MedMindServiceRegistry()

    registry._services[
        "clinic-001"
    ] = FakeService(
        tenant_context=None,
    )

    context = make_context(
        "clinic-001"
    )

    with pytest.raises(
        RuntimeError,
        match="missing tenant context",
    ):
        await registry.get(
            tenant_id="clinic-001",
            tenant_context=context,
        )


@pytest.mark.asyncio
async def test_registry_rejects_different_provider_context():
    registry = MedMindServiceRegistry()

    cached_context = make_context(
        "clinic-001"
    )

    registry._services[
        "clinic-001"
    ] = FakeService(
        tenant_context=cached_context,
    )

    requested_context = make_context(
        "clinic-001",
        provider_id=uuid4(),
    )

    with pytest.raises(
        RuntimeError,
        match="does not match requested",
    ):
        await registry.get(
            tenant_id="clinic-001",
            tenant_context=requested_context,
        )

@pytest.mark.asyncio
async def test_concurrent_registry_get_creates_service_once(
    monkeypatch,
):
    context = make_context(
        "clinic-001"
    )

    create_started = asyncio.Event()
    release_create = asyncio.Event()

    created = []

    async def fake_create(
        **kwargs,
    ):
        create_started.set()

        await release_create.wait()

        service = FakeService(
            tenant_context=(
                kwargs["tenant_context"]
            ),
        )

        created.append(service)

        return service

    monkeypatch.setattr(
        "app.services.medmind_registry."
        "MedMindService.create",
        fake_create,
    )

    registry = MedMindServiceRegistry()

    first_task = asyncio.create_task(
        registry.get(
            tenant_id="clinic-001",
            tenant_context=context,
        )
    )

    # Make sure the first request is already
    # creating the tenant service.
    await create_started.wait()

    second_task = asyncio.create_task(
        registry.get(
            tenant_id="clinic-001",
            tenant_context=context,
        )
    )

    # Give the second request a chance to reach
    # the registry lock.
    await asyncio.sleep(0)

    release_create.set()

    first, second = await asyncio.gather(
        first_task,
        second_task,
    )

    assert first is second
    assert len(created) == 1        