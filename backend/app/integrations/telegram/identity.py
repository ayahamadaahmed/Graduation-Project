def build_telegram_session_id(
    *,
    chat_id: int,
    user_id: int,
) -> str:
    """
    A stable conversation identity.

    Including user_id prevents users inside the
    same Telegram group from sharing state.
    """

    return (
        f"telegram:"
        f"{chat_id}:"
        f"{user_id}"
    )


def build_public_thread_id(
    *,
    session_id: str,
) -> str:
    return (
        f"public:{session_id}"
    )


def build_booking_thread_id(
    *,
    tenant_key: str,
    session_id: str,
) -> str:
    return (
        f"{tenant_key}:"
        f"{session_id}"
    )