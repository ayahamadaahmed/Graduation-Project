from __future__ import annotations

import logging

import httpx

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.api.dependencies import (
    AppointmentServiceDependency,
    CurrentProvider,
)
from app.security.service_auth import (
    AuthorizedService,
    require_gateway_service,
)

from app.integrations.n8n_whatsapp_client import (
    N8NWhatsAppClient,
)

from app.schemas.post_call import (
    PostCallBookingConfirmationRequest,
    PostCallBookingConfirmationResponse,
)

from app.services.post_call_service import (
    PostCallService,
)

from app.services.whatsapp_formatter import (
    WhatsAppFormatter,
)


logger = logging.getLogger(
    "medmind.post_call"
)


router = APIRouter(
    prefix="/post-call",
    tags=["post-call"],
)


@router.post(
    "/booking-confirmation",
    dependencies=[Depends(require_gateway_service)],  # token + gateway identity checked before any tenant DB lookup
    response_model=
        PostCallBookingConfirmationResponse,
)
async def booking_confirmation_post_call(
    data:
        PostCallBookingConfirmationRequest,

    provider:
        CurrentProvider,

    # Only a trusted gateway allowed for this tenant may trigger patient
    # notifications (checked before any booking lookup or WhatsApp call).
    caller:
        AuthorizedService,

    appointment_service:
        AppointmentServiceDependency,
) -> PostCallBookingConfirmationResponse:

    # ========================================================
    # 1. Load trusted appointment data from DB
    # ========================================================

    service = (
        PostCallService(
            appointment_service=
                appointment_service,
        )
    )

    notification = (
        service.prepare_booking_confirmation(
            provider_id=
                provider.id,

            appointment_reference=
                data.appointment_reference,
        )
    )

    # ========================================================
    # 3. Dispatch to n8n
    # ========================================================

    client = (
        N8NWhatsAppClient()
    )

    try:

        try:

            delivery = await (
                client
                .send_booking_confirmation(
                    provider_id=
                        provider.id,

                    payload=
                        notification,
                )
            )

        except (
            httpx.HTTPError,
            RuntimeError,
        ) as exc:

            # ------------------------------------------------
            # Booking itself has already succeeded.
            #
            # A WhatsApp failure must NOT cancel or rollback
            # the appointment.
            # ------------------------------------------------

            logger.exception(
                "post_call_whatsapp_delivery_failed "
                "provider_id=%s "
                "appointment_reference=%s",
                provider.id,
                notification
                .appointment_reference,
            )

            raise HTTPException(
                status_code=
                    status.HTTP_503_SERVICE_UNAVAILABLE,

                detail={
                    "code":
                        "WHATSAPP_DELIVERY_UNAVAILABLE",

                    "message":
                        (
                            "The booking was confirmed, "
                            "but the WhatsApp notification "
                            "could not be queued."
                        ),
                },
            ) from exc

    finally:

        # ====================================================
        # Always close the HTTP client
        # ====================================================

        await (
            client.close()
        )

    # ========================================================
    # 4. Successful delivery handoff
    # ========================================================

    logger.info(
        "post_call_whatsapp_delivery_accepted "
        "provider_id=%s "
        "appointment_reference=%s "
        "event_id=%s",
        provider.id,
        notification
        .appointment_reference,
        delivery[
            "event_id"
        ],
    )

    # ========================================================
    # Important:
    #
    # Do NOT return:
    # - patient phone
    # - patient name
    # - national ID
    # - full WhatsApp payload
    #
    # Voice Gateway only needs acknowledgement.
    # ========================================================

    return (
        PostCallBookingConfirmationResponse(
            appointment_reference=(
                notification
                .appointment_reference
            ),

            prepared=True,
        )
    )