import pytest

from voice_gateway.main import (
    POST_CALL_APPOINTMENT_REFERENCE_KEY,
    POST_CALL_BOOKING_CONFIRMED,
    POST_CALL_EVENT_KEY,
    capture_post_call_booking_event,
)


from voice_gateway.main import (
    dispatch_post_call_event,
)

def test_successful_booking_arms_post_call_event():

    state = {
        "stage": "awaiting_confirmation",
    }

    result = {
        "stage":
            "booking_completed",

        "response_type":
            "booking_created",

        "appointment_reference":
            "APT-260827-ABC123",
    }

    captured = (
        capture_post_call_booking_event(
            result=result,
            conversation_state=state,
            channel_id="test-channel",
        )
    )

    assert captured is True

    assert (
        state[
            POST_CALL_EVENT_KEY
        ]
        ==
        POST_CALL_BOOKING_CONFIRMED
    )

    assert (
        state[
            POST_CALL_APPOINTMENT_REFERENCE_KEY
        ]
        ==
        "APT-260827-ABC123"
    )


def test_non_booking_response_does_not_arm_event():

    state = {}

    result = {
        "stage":
            "awaiting_confirmation",

        "response_type":
            "booking_confirmation",

        "appointment_reference":
            None,
    }

    captured = (
        capture_post_call_booking_event(
            result=result,
            conversation_state=state,
            channel_id="test-channel",
        )
    )

    assert captured is False

    assert (
        POST_CALL_EVENT_KEY
        not in state
    )

    assert (
        POST_CALL_APPOINTMENT_REFERENCE_KEY
        not in state
    )


def test_booking_without_reference_fails_closed():

    state = {}

    result = {
        "stage":
            "booking_completed",

        "response_type":
            "booking_created",

        "appointment_reference":
            None,
    }

    captured = (
        capture_post_call_booking_event(
            result=result,
            conversation_state=state,
            channel_id="test-channel",
        )
    )

    assert captured is False

    assert (
        POST_CALL_EVENT_KEY
        not in state
    )


def test_wrong_stage_does_not_arm_event():

    state = {}

    result = {
        "stage":
            "awaiting_confirmation",

        "response_type":
            "booking_created",

        "appointment_reference":
            "APT-260827-ABC123",
    }

    captured = (
        capture_post_call_booking_event(
            result=result,
            conversation_state=state,
            channel_id="test-channel",
        )
    )

    assert captured is False

    assert (
        POST_CALL_EVENT_KEY
        not in state
    )


class FakePostCallClient:

    def __init__(
        self,
        *,
        should_fail: bool = False,
    ) -> None:

        self.should_fail = (
            should_fail
        )

        self.calls = []

    async def send_booking_confirmation(
        self,
        *,
        tenant_id: str,
        appointment_reference: str,
    ):

        self.calls.append(
            {
                "tenant_id":
                    tenant_id,

                "appointment_reference":
                    appointment_reference,
            }
        )

        if self.should_fail:

            raise RuntimeError(
                "fake post-call failure"
            )

        return {
            "status":
                "accepted",

            "appointment_reference":
                appointment_reference,
        }    


@pytest.mark.asyncio
async def test_armed_post_call_event_is_dispatched_once():

    state = {
        POST_CALL_EVENT_KEY:
            POST_CALL_BOOKING_CONFIRMED,

        POST_CALL_APPOINTMENT_REFERENCE_KEY:
            "APT-260827-ABC123",
    }

    client = (
        FakePostCallClient()
    )

    dispatched = await (
        dispatch_post_call_event(
            conversation_state=
                state,

            tenant_id=
                "clinic001",

            channel_id=
                "test-channel",

            client=
                client,
        )
    )

    assert dispatched is True

    assert client.calls == [
        {
            "tenant_id":
                "clinic001",

            "appointment_reference":
                "APT-260827-ABC123",
        }
    ]

    assert (
        POST_CALL_EVENT_KEY
        not in state
    )

    assert (
        POST_CALL_APPOINTMENT_REFERENCE_KEY
        not in state
    )


@pytest.mark.asyncio
async def test_post_call_event_cannot_dispatch_twice():

    state = {
        POST_CALL_EVENT_KEY:
            POST_CALL_BOOKING_CONFIRMED,

        POST_CALL_APPOINTMENT_REFERENCE_KEY:
            "APT-260827-ABC123",
    }

    client = (
        FakePostCallClient()
    )

    first = await (
        dispatch_post_call_event(
            conversation_state=
                state,

            tenant_id=
                "clinic001",

            channel_id=
                "test-channel",

            client=
                client,
        )
    )

    second = await (
        dispatch_post_call_event(
            conversation_state=
                state,

            tenant_id=
                "clinic001",

            channel_id=
                "test-channel",

            client=
                client,
        )
    )

    assert first is True
    assert second is False

    assert (
        len(
            client.calls
        )
        == 1
    )

@pytest.mark.asyncio
async def test_post_call_failure_does_not_raise():

    state = {
        POST_CALL_EVENT_KEY:
            POST_CALL_BOOKING_CONFIRMED,

        POST_CALL_APPOINTMENT_REFERENCE_KEY:
            "APT-260827-ABC123",
    }

    client = (
        FakePostCallClient(
            should_fail=True,
        )
    )

    dispatched = await (
        dispatch_post_call_event(
            conversation_state=
                state,

            tenant_id=
                "clinic001",

            channel_id=
                "test-channel",

            client=
                client,
        )
    )

    assert dispatched is False

    assert (
        len(
            client.calls
        )
        == 1
    )        