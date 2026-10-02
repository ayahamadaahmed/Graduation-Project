from dataclasses import dataclass
from uuid import uuid4

from medmind.core.tools import (
    select_read_tools,
)
from medmind.tenancy.capabilities import (
    ProviderType,
    build_tenant_capabilities,
)
from medmind.tenancy.context import (
    TenantContext,
)


@dataclass
class FakeTool:
    name: str


def make_tools():
    return [
        FakeTool("get_provider_info"),
        FakeTool("list_specialties"),
        FakeTool("list_doctors"),
        FakeTool("list_services"),
        FakeTool("list_available_slots"),
        FakeTool("create_appointment"),
    ]


def make_context(
    tenant_id: str,
    provider_type: ProviderType,
):
    return TenantContext(
        tenant_id=tenant_id,
        provider_id=uuid4(),
        provider_name="Test Provider",
        capabilities=build_tenant_capabilities(
            tenant_id=tenant_id,
            provider_type=provider_type,
        ),
    )


def tool_names(
    tools,
):
    return {
        tool.name
        for tool in tools
    }


def test_legacy_read_tool_selection_is_preserved():
    selected = select_read_tools(
        make_tools()
    )

    assert tool_names(
        selected
    ) == {
        "get_provider_info",
        "list_specialties",
        "list_doctors",
        "list_services",
        "list_available_slots",
    }


def test_clinic_receives_clinic_read_tools():
    context = make_context(
        "clinic-001",
        ProviderType.CLINIC,
    )

    selected = select_read_tools(
        make_tools(),
        tenant_context=context,
    )

    names = tool_names(
        selected
    )

    assert "get_provider_info" in names
    assert "list_specialties" in names
    assert "list_doctors" in names
    assert "list_services" in names
    assert "list_available_slots" in names

    assert "create_appointment" not in names


def test_lab_does_not_receive_doctor_or_specialty_tools():
    context = make_context(
        "lab-001",
        ProviderType.LAB,
    )

    selected = select_read_tools(
        make_tools(),
        tenant_context=context,
    )

    names = tool_names(
        selected
    )

    assert "get_provider_info" in names
    assert "list_services" in names
    assert "list_available_slots" in names

    assert "list_specialties" not in names
    assert "list_doctors" not in names


def test_write_tool_is_never_exposed_to_read_agent():
    context = make_context(
        "clinic-001",
        ProviderType.CLINIC,
    )

    selected = select_read_tools(
        make_tools(),
        tenant_context=context,
    )

    assert (
        "create_appointment"
        not in tool_names(
            selected
        )
    )