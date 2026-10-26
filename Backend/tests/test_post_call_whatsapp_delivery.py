from __future__ import annotations

from datetime import (
    date,
    time,
)
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routers import (
    post_call as post_call_router,
)
from app.security.service_auth import ServiceContext


def authorized_caller(provider):
    """An authenticated gateway. These tests call the handler directly, so the
    auth/tenant dependency itself is tested in tests/test_post_call_service_auth.py."""
    return ServiceContext(
        name="voice_gateway",
        allowed_tenants=frozenset({"clinic-001"}),
    )


from app.schemas.post_call import (
    PostCallBookingConfirmationRequest,
)


# ============================================================
# FAKE APPOINTMENT SERVICE
# ============================================================

class FakeAppointmentService:

    def __init__(
        self,
    ) -> None:

        self.calls = []

    def get_booking_by_reference(
        self,
        *,
        provider_id,
        appointment_reference,
    ):

        self.calls.append(
            {
                "provider_id":
                    provider_id,

                "appointment_reference":
                    appointment_reference,
            }
        )

        return SimpleNamespace(
            appointment_reference=
                appointment_reference,

            patient_name=
                "آية أحمد",

            phone=
                "01023456789",

            preferred_language=
                "ar",

            doctor_name=
                "دكتور ماهر محمود",

            specialty_name=
                "جلدية",

            service_name=
                "كشف جلدية",

            branch_name=
                "فرع الدقي",

            branch_medical_record_number=
                "DOK-2026-001",

            scheduled_date=
                date(
                    2026,
                    8,
                    28,
                ),

            start_time=
                time(
                    17,
                    0,
                ),

            end_time=
                time(
                    17,
                    30,
                ),

            status=
                "confirmed",

            channel=
                "voice",
        )


# ============================================================
# FAKE N8N CLIENT
# ============================================================

class FakeN8NWhatsAppClient:

    instances = []

    should_fail = False

    def __init__(
        self,
    ) -> None:

        self.calls = []

        self.closed = False

        self.__class__.instances.append(
            self
        )

    async def send_booking_confirmation(
        self,
        *,
        provider_id,
        payload,
    ):

        self.calls.append(
            {
                "provider_id":
                    provider_id,

                "payload":
                    payload,
            }
        )

        if self.__class__.should_fail:

            raise RuntimeError(
                "fake n8n failure"
            )

        return {
            "status":
                "accepted",

            "event_id":
                (
                    "booking_confirmation:"
                    f"{provider_id}:"
                    f"{payload.appointment_reference}"
                ),

            "http_status":
                200,
        }

    async def close(
        self,
    ) -> None:

        self.closed = True


# ============================================================
# HELPERS
# ============================================================

def make_request():

    return (
        PostCallBookingConfirmationRequest(
            event_type=
                "booking_confirmation",

            appointment_reference=
                "APT-260828-ABC123",

            source=
                "voice",
        )
    )


def make_provider():

    return SimpleNamespace(
        id=
            uuid4(),
    )


# ============================================================
# TEST 1
#
# SUCCESSFUL DELIVERY
# ============================================================

@pytest.mark.asyncio
async def test_post_call_endpoint_delivers_to_n8n(
    monkeypatch,
):

    FakeN8NWhatsAppClient.instances.clear()

    FakeN8NWhatsAppClient.should_fail = (
        False
    )

    monkeypatch.setattr(
        post_call_router,
        "N8NWhatsAppClient",
        FakeN8NWhatsAppClient,
    )

    provider = (
        make_provider()
    )

    appointment_service = (
        FakeAppointmentService()
    )

    result = await (
        post_call_router
        .booking_confirmation_post_call(
            data=
                make_request(),

            provider=
                provider,

            caller=
                authorized_caller(provider),

            appointment_service=
                appointment_service,
        )
    )

    # --------------------------------------------------------
    # Endpoint response
    # --------------------------------------------------------

    assert (
        result.status
        == "accepted"
    )

    assert (
        result.prepared
        is True
    )

    assert (
        result.appointment_reference
        == "APT-260828-ABC123"
    )

    # --------------------------------------------------------
    # Appointment was loaded using trusted provider scope
    # --------------------------------------------------------

    assert (
        appointment_service.calls
        == [
            {
                "provider_id":
                    provider.id,

                "appointment_reference":
                    "APT-260828-ABC123",
            }
        ]
    )

    # --------------------------------------------------------
    # N8N client
    # --------------------------------------------------------

    assert (
        len(
            FakeN8NWhatsAppClient.instances
        )
        == 1
    )

    client = (
        FakeN8NWhatsAppClient
        .instances[
            0
        ]
    )

    assert (
        len(
            client.calls
        )
        == 1
    )

    call = (
        client.calls[
            0
        ]
    )

    assert (
        call[
            "provider_id"
        ]
        == provider.id
    )

    # Local Egyptian number must have been converted
    # to E.164 before delivery.
    assert (
        call[
            "payload"
        ].recipient_phone
        == "+201023456789"
    )

    assert (
        call[
            "payload"
        ].language
        == "ar"
    )

    # The client receives structured booking data (n8n renders the text).
    assert (
        call[
            "payload"
        ].appointment_reference
        == "APT-260828-ABC123"
    )

    # Client must always close.
    assert (
        client.closed
        is True
    )


# ============================================================
# TEST 2
#
# N8N FAILURE
# ============================================================

@pytest.mark.asyncio
async def test_post_call_endpoint_returns_503_when_n8n_fails(
    monkeypatch,
):

    FakeN8NWhatsAppClient.instances.clear()

    FakeN8NWhatsAppClient.should_fail = (
        True
    )

    monkeypatch.setattr(
        post_call_router,
        "N8NWhatsAppClient",
        FakeN8NWhatsAppClient,
    )

    provider = (
        make_provider()
    )

    appointment_service = (
        FakeAppointmentService()
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        await (
            post_call_router
            .booking_confirmation_post_call(
                data=
                    make_request(),

                provider=
                    provider,

                caller=
                    authorized_caller(provider),

                appointment_service=
                    appointment_service,
            )
        )

    assert (
        exc_info.value.status_code
        == 503
    )

    assert (
        exc_info.value.detail[
            "code"
        ]
        == "WHATSAPP_DELIVERY_UNAVAILABLE"
    )

    # --------------------------------------------------------
    # Appointment lookup still happened successfully.
    #
    # This failure represents notification failure only.
    # It does NOT roll back or cancel the booking.
    # --------------------------------------------------------

    assert (
        len(
            appointment_service.calls
        )
        == 1
    )

    assert (
        len(
            FakeN8NWhatsAppClient.instances
        )
        == 1
    )

    client = (
        FakeN8NWhatsAppClient
        .instances[
            0
        ]
    )

    assert (
        len(
            client.calls
        )
        == 1
    )

    # Client must also close on failure.
    assert (
        client.closed
        is True
    )