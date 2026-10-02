from __future__ import annotations

from datetime import datetime as RealDateTime
from uuid import uuid4

import medmind.prompts.system as system_module

from medmind.prompts.system import (
    build_system_prompt,
)
from medmind.tenancy.capabilities import (
    Capability,
    ProviderType,
    build_tenant_capabilities,
)
from medmind.tenancy.context import (
    TenantContext,
)


class FakeState:

    def safe_llm_context(
        self,
    ) -> dict:
        return {
            "stage": "new",
            "active_capability": None,
        }


def make_context(
    *,
    tenant_id: str,
    provider_name: str,
    provider_type: ProviderType,
    timezone: str = "Africa/Cairo",
) -> TenantContext:

    return TenantContext(
        tenant_id=tenant_id,
        provider_id=uuid4(),
        provider_name=provider_name,
        capabilities=build_tenant_capabilities(
            tenant_id=tenant_id,
            provider_type=provider_type,
        ),
        timezone=timezone,
    )


def test_clinic_prompt_contains_provider_context():

    context = make_context(
        tenant_id="clinic-001",
        provider_name="Test Clinic",
        provider_type=ProviderType.CLINIC,
    )

    prompt = build_system_prompt(
        language="en",
        state=FakeState(),
        tenant_context=context,
    )

    assert "Test Clinic" in prompt
    assert '"provider_type": "clinic"' in prompt

    assert (
        Capability.DOCTOR_SEARCH.value
        in prompt
    )

    assert (
        Capability.APPOINTMENT_AVAILABLE_SLOTS.value
        in prompt
    )

    assert (
        Capability.LAB_RESULT_LOOKUP.value
        not in prompt
    )


def test_lab_prompt_contains_lab_capabilities_only():

    context = make_context(
        tenant_id="lab-001",
        provider_name="Test Lab",
        provider_type=ProviderType.LAB,
    )

    prompt = build_system_prompt(
        language="en",
        state=FakeState(),
        tenant_context=context,
    )

    assert "Test Lab" in prompt
    assert '"provider_type": "lab"' in prompt

    assert (
        Capability.LAB_RESULT_LOOKUP.value
        in prompt
    )

    assert (
        Capability.LAB_TEST_PREPARATION.value
        in prompt
    )

    assert (
        Capability.DOCTOR_SEARCH.value
        not in prompt
    )


def test_old_development_phase_instruction_is_removed():

    context = make_context(
        tenant_id="clinic-001",
        provider_name="Test Clinic",
        provider_type=ProviderType.CLINIC,
    )

    prompt = build_system_prompt(
        language="en",
        state=FakeState(),
        tenant_context=context,
    )

    assert (
        "Appointment write actions are not enabled"
        not in prompt
    )

    assert (
        "CURRENT DEVELOPMENT PHASE"
        not in prompt
    )


def test_prompt_uses_provider_timezone(
    monkeypatch,
):

    observed = {}

    class FakeDateTime:

        @classmethod
        def now(
            cls,
            tz,
        ):
            observed["timezone"] = getattr(
                tz,
                "key",
                None,
            )

            return RealDateTime(
                2026,
                9,
                13,
                20,
                30,
                tzinfo=tz,
            )

    monkeypatch.setattr(
        system_module,
        "datetime",
        FakeDateTime,
    )

    context = make_context(
        tenant_id="hospital-001",
        provider_name="Test Hospital",
        provider_type=ProviderType.HOSPITAL,
        timezone="Asia/Riyadh",
    )

    prompt = build_system_prompt(
        language="en",
        state=FakeState(),
        tenant_context=context,
    )

    assert (
        observed["timezone"]
        == "Asia/Riyadh"
    )

    assert (
        '"timezone": "Asia/Riyadh"'
        in prompt
    )

    assert "2026-09-13" in prompt
    assert "20:30" in prompt


def test_legacy_prompt_without_tenant_context_still_works():

    prompt = build_system_prompt(
        language="en",
        state=FakeState(),
        tenant_context=None,
    )

    assert isinstance(
        prompt,
        str,
    )

    assert (
        "Provider context: legacy/unavailable"
        in prompt
    )

    assert (
        "CURRENT SESSION STATE"
        in prompt
    )