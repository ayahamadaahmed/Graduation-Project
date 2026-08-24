from app.integrations.telegram.identity import (
    build_booking_thread_id,
    build_public_thread_id,
    build_telegram_session_id,
)


def test_telegram_session_is_user_scoped():
    first = build_telegram_session_id(
        chat_id=100,
        user_id=10,
    )

    second = build_telegram_session_id(
        chat_id=100,
        user_id=20,
    )

    assert first != second


def test_public_and_booking_threads_are_separate():
    session_id = build_telegram_session_id(
        chat_id=100,
        user_id=10,
    )

    public_thread = build_public_thread_id(
        session_id=session_id,
    )

    booking_thread = build_booking_thread_id(
        tenant_key="clinic-001",
        session_id=session_id,
    )

    assert public_thread != booking_thread

    assert public_thread == (
        "public:telegram:100:10"
    )

    assert booking_thread == (
        "clinic-001:telegram:100:10"
    )