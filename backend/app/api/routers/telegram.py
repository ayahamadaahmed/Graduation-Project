from __future__ import annotations

from collections import deque
import logging
import re
import secrets
from threading import Lock
import unicodedata
from typing import Any

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
    status,
)

from ai_agent.operation_lifecycle import (
    OPERATION_INTENTS,
    abandon_active_operation_updates,
    explicit_operation_from_message,
    public_restart_reason,
)

from app.api.dependencies import (
    CatalogServiceDependency,
    TelegramClientDependency,
)

from app.core.config import (
    get_settings,
)

from app.integrations.telegram.identity import (
    build_booking_thread_id,
    build_public_thread_id,
    build_telegram_session_id,
)

from app.schemas.telegram import (
    TelegramUpdate,
)


logger = logging.getLogger(
    __name__
)


router = APIRouter(
    prefix="/telegram",
    tags=["telegram"],
)


# ============================================================
# TELEGRAM UPDATE IDEMPOTENCY
# ============================================================
#
# Telegram can retry the same update.
# Process each update_id only once.
#
# Current implementation is process-local and suitable
# for the current single-worker development/demo runtime.
#
# Production:
# Redis/database-backed idempotency.
# ============================================================

_TELEGRAM_UPDATE_CACHE_LIMIT = 10_000

_processed_update_ids: set[int] = set()

_processed_update_order: deque[int] = deque()

_processed_update_lock = Lock()


def _claim_telegram_update(
    update_id: int,
) -> bool:

    with _processed_update_lock:

        if update_id in _processed_update_ids:
            return False

        _processed_update_ids.add(
            update_id
        )

        _processed_update_order.append(
            update_id
        )

        while (
            len(_processed_update_order)
            > _TELEGRAM_UPDATE_CACHE_LIMIT
        ):
            expired_update_id = (
                _processed_update_order.popleft()
            )

            _processed_update_ids.discard(
                expired_update_id
            )

    return True


# ============================================================
# PENDING HEALTHCARE REQUEST
# ============================================================
#
# Example:
#
# User:
#   "عايزة اغير الحجز APT-..."
#
# The operation starts before Provider/Branch selection.
#
# We save the original message:
#
# pending request
#       ↓
# Provider
#       ↓
# Branch
#       ↓
# automatically resume original message
#
# The patient does not need to repeat it.
# ============================================================

_PENDING_REQUEST_CACHE_LIMIT = 5_000

_pending_requests: dict[
    str,
    str,
] = {}

_pending_request_order: deque[
    str
] = deque()

_pending_request_lock = Lock()


def _remember_pending_request(
    session_id: str,
    text: str,
) -> None:

    normalized_text = str(
        text or ""
    ).strip()

    if not normalized_text:
        return

    with _pending_request_lock:

        if (
            session_id
            not in _pending_requests
        ):
            _pending_request_order.append(
                session_id
            )

        _pending_requests[
            session_id
        ] = normalized_text

        while (
            len(_pending_request_order)
            > _PENDING_REQUEST_CACHE_LIMIT
        ):
            expired_session_id = (
                _pending_request_order.popleft()
            )

            _pending_requests.pop(
                expired_session_id,
                None,
            )


def _get_pending_request(
    session_id: str,
) -> str | None:

    with _pending_request_lock:

        return _pending_requests.get(
            session_id
        )


def _clear_pending_request(
    session_id: str,
) -> None:

    with _pending_request_lock:

        removed = _pending_requests.pop(
            session_id,
            None,
        )

        if removed is None:
            return

        try:
            _pending_request_order.remove(
                session_id
            )

        except ValueError:
            pass


# ============================================================
# FRESH PROVIDER SELECTION
# ============================================================
#
# Important distinction:
#
# 1. Provider selected just now
#    -> may be used for the NEXT operation.
#
# 2. Provider stored from an old Telegram session
#    -> must NOT silently be reused.
#
#
# Example:
#
# /start
#   ↓
# choose provider
#   ↓
# choose branch
#   ↓
# "عايزة احجز"
#
# This must go directly to Booking Graph.
#
#
# But:
#
# old provider from 3 days ago
#   ↓
# "عايزة اغير الحجز"
#
# must ask Provider again.
#
#
# A fresh selection is consumed once when a new
# top-level operation begins.
# ============================================================

_PROVIDER_SELECTION_CACHE_LIMIT = 5_000

_fresh_provider_sessions: set[
    str
] = set()

_fresh_provider_order: deque[
    str
] = deque()

_fresh_provider_lock = Lock()


def _mark_provider_selection_fresh(
    session_id: str,
) -> None:

    with _fresh_provider_lock:

        if (
            session_id
            in _fresh_provider_sessions
        ):
            return

        _fresh_provider_sessions.add(
            session_id
        )

        _fresh_provider_order.append(
            session_id
        )

        while (
            len(_fresh_provider_order)
            > _PROVIDER_SELECTION_CACHE_LIMIT
        ):
            expired_session_id = (
                _fresh_provider_order.popleft()
            )

            _fresh_provider_sessions.discard(
                expired_session_id
            )


def _consume_provider_selection_fresh(
    session_id: str,
) -> bool:
    """
    Return True once for a freshly selected
    Provider/Branch.

    Once consumed, the same selection cannot
    silently start another operation.
    """

    with _fresh_provider_lock:

        if (
            session_id
            not in _fresh_provider_sessions
        ):
            return False

        _fresh_provider_sessions.discard(
            session_id
        )

        try:
            _fresh_provider_order.remove(
                session_id
            )

        except ValueError:
            pass

    return True


def _clear_provider_selection_fresh(
    session_id: str,
) -> None:

    with _fresh_provider_lock:

        if (
            session_id
            not in _fresh_provider_sessions
        ):
            return

        _fresh_provider_sessions.discard(
            session_id
        )

        try:
            _fresh_provider_order.remove(
                session_id
            )

        except ValueError:
            pass


# ============================================================
# PUBLIC FLOW
# ============================================================

PUBLIC_RESTART_STAGES = frozenset(
    {
        "booking_completed",
        "search_completed",
        "lookup_completed",
        "cancellation_completed",
        "reschedule_completed",
        "information_completed",
        "already_cancelled",
        "cancelled_by_user",
    }
)


# ============================================================
# GREETINGS
# ============================================================

_PURE_GREETINGS = frozenset(
    {
        "السلام عليكم",
        "السلام عليكم ورحمه الله",
        "السلام عليكم ورحمه الله وبركاته",
        "سلام عليكم",
        "سلا عليكم",
        "سلام",
        "اهلا",
        "اهلين",
        "مرحبا",
        "هاي",
        "ازيك",
        "صباح الخير",
        "مساء الخير",
        "hello",
        "hi",
        "hey",
    }
)


def _normalize_short_message(
    value: str,
) -> str:

    decomposed = unicodedata.normalize(
        "NFKD",
        value,
    )

    without_marks = "".join(
        character
        for character in decomposed
        if (
            unicodedata.category(
                character
            )
            != "Mn"
        )
    )

    without_punctuation = re.sub(
        r"[^\w\s]",
        " ",
        without_marks.lower(),
        flags=re.UNICODE,
    )

    return " ".join(
        without_punctuation.split()
    )


def _greeting_reply(
    message: str,
) -> str | None:

    normalized = (
        _normalize_short_message(
            message
        )
    )

    if (
        normalized
        not in _PURE_GREETINGS
    ):
        return None

    if normalized.startswith(
        (
            "السلام",
            "سلام",
            "سلا",
        )
    ):
        return (
            "وعليكم السلام ورحمة الله "
            "وبركاته 👋"
        )

    if normalized.startswith(
        "صباح"
    ):
        return "صباح النور 👋"

    if normalized.startswith(
        "مساء"
    ):
        return "مساء النور 👋"

    if normalized in {
        "hello",
        "hi",
        "hey",
    }:
        return "Hello! 👋"

    return "أهلًا وسهلًا بيك 👋"


# ============================================================
# SECURITY
# ============================================================

def _validate_webhook_secret(
    received_secret: str | None,
) -> None:

    configured_secret = (
        get_settings()
        .telegram_webhook_secret
        .strip()
    )

    if not configured_secret:

        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "TELEGRAM_NOT_CONFIGURED",

                "message":
                    (
                        "Telegram webhook security "
                        "is not configured."
                    ),
            },
        )

    if (
        received_secret is None
        or not secrets.compare_digest(
            received_secret,
            configured_secret,
        )
    ):

        raise HTTPException(
            status_code=403,
            detail={
                "code":
                    "INVALID_TELEGRAM_SECRET",

                "message":
                    (
                        "Invalid Telegram "
                        "webhook secret."
                    ),
            },
        )


# ============================================================
# GRAPH RESOLUTION
# ============================================================

def _get_public_graph(
    request: Request,
) -> Any:

    graph = getattr(
        request.app.state,
        "public_onboarding_graph",
        None,
    )

    if graph is None:

        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "PUBLIC_AGENT_UNAVAILABLE",

                "message":
                    (
                        "Public onboarding is "
                        "currently unavailable."
                    ),
            },
        )

    return graph


def _get_booking_graph(
    request: Request,
) -> Any:

    graph = getattr(
        request.app.state,
        "booking_graph",
        None,
    )

    if graph is None:

        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "BOOKING_AGENT_UNAVAILABLE",

                "message":
                    (
                        "Booking assistant is "
                        "currently unavailable."
                    ),
            },
        )

    return graph


# ============================================================
# OPERATION HELPERS
# ============================================================

def _requested_operation(
    text: str,
) -> str | None:

    requested = (
        explicit_operation_from_message(
            text
        )
    )

    if (
        requested
        not in OPERATION_INTENTS
    ):
        return None

    return requested


def _message_starts_operation(
    text: str,
) -> bool:

    return (
        _requested_operation(
            text
        )
        is not None
    )


def _should_restart_public_onboarding(
    result: dict,
) -> bool:

    stage = str(
        result.get(
            "stage"
        )
        or ""
    )

    return (
        stage
        in PUBLIC_RESTART_STAGES
    )


# ============================================================
# ONBOARDING HELPERS
# ============================================================

def _onboarding_is_ready(
    state: dict[str, Any],
) -> bool:

    onboarding_completed = bool(
        state.get(
            "onboarding_completed",
            False,
        )
    )

    tenant_key = str(
        state.get(
            "tenant_key"
        )
        or ""
    ).strip()

    provider_id = str(
        state.get(
            "provider_id"
        )
        or ""
    ).strip()

    branch_id = str(
        state.get(
            "branch_id"
        )
        or ""
    ).strip()

    return bool(
        onboarding_completed
        and tenant_key
        and provider_id
        and branch_id
    )


def _public_config(
    *,
    thread_id: str,
    catalog_service: Any,
) -> dict:

    return {
        "configurable": {
            "thread_id":
                thread_id,

            "catalog_service":
                catalog_service,
        }
    }


def _booking_config(
    *,
    tenant_key: str,
    session_id: str,
) -> dict:

    return {
        "configurable": {
            "thread_id":
                build_booking_thread_id(
                    tenant_key=tenant_key,
                    session_id=session_id,
                ),
        }
    }


async def _public_state(
    *,
    graph: Any,
    config: dict,
) -> dict:

    snapshot = await graph.aget_state(
        config
    )

    values = getattr(
        snapshot,
        "values",
        {},
    )

    if not isinstance(
        values,
        dict,
    ):
        return {}

    return values


async def _booking_state(
    *,
    graph: Any,
    config: dict,
) -> dict:

    state_reader = getattr(
        graph,
        "aget_state",
        None,
    )

    if not callable(
        state_reader
    ):
        return {}

    snapshot = await state_reader(
        config
    )

    values = getattr(
        snapshot,
        "values",
        {},
    )

    if not isinstance(
        values,
        dict,
    ):
        return {}

    return values


async def _save_abandoned_booking_state(
    *,
    graph: Any,
    config: dict,
    state: dict,
    reason: str,
) -> None:

    state_updater = getattr(
        graph,
        "aupdate_state",
        None,
    )

    if not callable(
        state_updater
    ):

        logger.warning(
            (
                "Booking graph does not support "
                "aupdate_state; abandoned operation "
                "will be reset on its next graph turn."
            )
        )

        return

    await state_updater(
        config,
        abandon_active_operation_updates(
            state,
            reason=reason,
        ),
    )


async def _send_result(
    *,
    telegram_client: Any,
    chat_id: int,
    result: dict,
) -> None:

    reply = str(
        result.get(
            "reply"
        )
        or ""
    ).strip()

    if not reply:

        reply = (
            "مقدرتش أنفذ الطلب دلوقتي. "
            "حاولي تاني."
        )

    reply_markup = result.get(
        "reply_markup"
    )

    await telegram_client.send_message(
        chat_id=chat_id,
        text=reply,
        reply_markup=(
            reply_markup
            if isinstance(
                reply_markup,
                dict,
            )
            else None
        ),
    )


async def _start_onboarding(
    *,
    graph: Any,
    session_id: str,
    config: dict,
) -> dict:

    result = await graph.ainvoke(
        {
            "session_id":
                session_id,

            "channel":
                "telegram",

            "language":
                "ar",

            "user_message":
                "/start",

            "callback_data":
                "restart:onboarding",
        },
        config=config,
    )

    if not isinstance(
        result,
        dict,
    ):

        raise RuntimeError(
            (
                "Invalid public "
                "onboarding result."
            )
        )

    return result


# ============================================================
# BOOKING GRAPH
# ============================================================

async def _invoke_booking_turn(
    *,
    graph: Any,
    onboarding: dict[str, Any],
    session_id: str,
    text: str,
) -> dict[str, Any]:

    tenant_key = str(
        onboarding.get(
            "tenant_key"
        )
        or ""
    ).strip()

    provider_id = str(
        onboarding.get(
            "provider_id"
        )
        or ""
    ).strip()

    branch_id = str(
        onboarding.get(
            "branch_id"
        )
        or ""
    ).strip()

    if (
        not tenant_key
        or not provider_id
        or not branch_id
    ):

        raise RuntimeError(
            (
                "Cannot invoke booking graph "
                "before Provider/Branch "
                "selection is complete."
            )
        )

    config = _booking_config(
        tenant_key=tenant_key,
        session_id=session_id,
    )

    logger.info(
        (
            "telegram_booking_context "
            "tenant_key=%s "
            "provider_id=%s "
            "branch_id=%s "
            "session_id=%s"
        ),
        tenant_key,
        provider_id,
        branch_id,
        session_id,
    )

    result = await graph.ainvoke(
        {
            "tenant_id":
                tenant_key,

            "provider_id":
                provider_id,

            "branch_id":
                branch_id,

            "branch_code":
                onboarding.get(
                    "branch_code"
                ),

            "branch_name":
                onboarding.get(
                    "branch_name"
                ),

            "session_id":
                session_id,

            "channel":
                "telegram",

            "user_message":
                text,
        },
        config=config,
    )

    if not isinstance(
        result,
        dict,
    ):

        raise RuntimeError(
            "Invalid booking agent result."
        )

    return result


# ============================================================
# WEBHOOK
# ============================================================

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
)
async def telegram_webhook(
    update: TelegramUpdate,

    request: Request,

    catalog_service: (
        CatalogServiceDependency
    ),

    telegram_client: (
        TelegramClientDependency
    ),

    telegram_secret: str | None = Header(
        default=None,
        alias=(
            "X-Telegram-Bot-Api-Secret-Token"
        ),
    ),
) -> dict[str, bool]:

    # ========================================================
    # SECURITY
    # ========================================================

    _validate_webhook_secret(
        telegram_secret
    )

    # ========================================================
    # IDEMPOTENCY
    # ========================================================

    if not _claim_telegram_update(
        update.update_id
    ):

        logger.info(
            (
                "telegram_duplicate_update_ignored "
                "update_id=%s"
            ),
            update.update_id,
        )

        return {
            "ok": True,
        }

    public_graph = _get_public_graph(
        request
    )

    booking_graph = _get_booking_graph(
        request
    )

    # ========================================================
    # CALLBACK QUERY
    # ========================================================

    if (
        update.callback_query
        is not None
    ):

        callback = (
            update.callback_query
        )

        if callback.message is None:

            return {
                "ok": True,
            }

        chat_id = (
            callback.message.chat.id
        )

        user_id = (
            callback.from_user.id
        )

        session_id = (
            build_telegram_session_id(
                chat_id=chat_id,
                user_id=user_id,
            )
        )

        public_thread_id = (
            build_public_thread_id(
                session_id=session_id
            )
        )

        public_config = (
            _public_config(
                thread_id=public_thread_id,
                catalog_service=(
                    catalog_service
                ),
            )
        )

        await (
            telegram_client
            .answer_callback_query(
                callback_query_id=(
                    callback.id
                )
            )
        )

        try:

            result = (
                await public_graph.ainvoke(
                    {
                        "session_id":
                            session_id,

                        "channel":
                            "telegram",

                        "callback_data":
                            callback.data
                            or "",
                    },
                    config=public_config,
                )
            )

            if not isinstance(
                result,
                dict,
            ):

                raise RuntimeError(
                    (
                        "Invalid public "
                        "onboarding result."
                    )
                )

            # Show current onboarding result:
            #
            # provider selected
            # branch selected
            # etc.
            await _send_result(
                telegram_client=(
                    telegram_client
                ),
                chat_id=chat_id,
                result=result,
            )

            # =================================================
            # PROVIDER + BRANCH COMPLETE
            # =================================================

            # ============================================================
            # Read the persisted onboarding state AFTER processing
            # the callback.
            #
            # The callback result may contain only reply/UI fields.
            # The persisted graph state is the source of truth for:
            #
            # onboarding_completed
            # tenant_key
            # provider_id
            # branch_id
            # ============================================================

            resolved_onboarding = (
                await _public_state(
                    graph=public_graph,
                    config=public_config,
                )
            )

            if _onboarding_is_ready(
                resolved_onboarding
            ):

                pending_text = (
                    _get_pending_request(
                        session_id
                    )
                )

                # ========================================================
                # CASE 1:
                # Operation requested before provider selection.
                #
                # Example:
                #
                # "عايزة اغير الحجز APT-..."
                #       ↓
                # Provider
                #       ↓
                # Branch
                #       ↓
                # Resume original request automatically.
                # ========================================================

                if pending_text is not None:

                    _clear_provider_selection_fresh(
                        session_id
                    )

                    logger.info(
                        (
                            "telegram_pending_operation_resume "
                            "session_id=%s "
                            "tenant_key=%s "
                            "provider_id=%s "
                            "branch_id=%s"
                        ),
                        session_id,
                        resolved_onboarding.get(
                            "tenant_key"
                        ),
                        resolved_onboarding.get(
                            "provider_id"
                        ),
                        resolved_onboarding.get(
                            "branch_id"
                        ),
                    )

                    booking_result = (
                        await _invoke_booking_turn(
                            graph=booking_graph,
                            onboarding=(
                                resolved_onboarding
                            ),
                            session_id=session_id,
                            text=pending_text,
                        )
                    )

                    await _send_result(
                        telegram_client=(
                            telegram_client
                        ),
                        chat_id=chat_id,
                        result=booking_result,
                    )

                    _clear_pending_request(
                        session_id
                    )

                    if (
                        _should_restart_public_onboarding(
                            booking_result
                        )
                    ):

                        restart_result = (
                            await _start_onboarding(
                                graph=public_graph,
                                session_id=session_id,
                                config=public_config,
                            )
                        )

                        _clear_provider_selection_fresh(
                            session_id
                        )

                        await _send_result(
                            telegram_client=(
                                telegram_client
                            ),
                            chat_id=chat_id,
                            result=restart_result,
                        )

                # ========================================================
                # CASE 2:
                # User selected Provider/Branch first.
                #
                # /start
                #   ↓
                # Provider
                #   ↓
                # Branch
                #   ↓
                # "عايزة أحجز جلدية"
                #
                # Mark this selection as fresh and allow it to start
                # exactly one operation.
                # ========================================================

                else:

                    _mark_provider_selection_fresh(
                        session_id
                    )

                    logger.info(
                        (
                            "telegram_provider_selection_ready "
                            "session_id=%s "
                            "tenant_key=%s "
                            "provider_id=%s "
                            "branch_id=%s"
                        ),
                        session_id,
                        resolved_onboarding.get(
                            "tenant_key"
                        ),
                        resolved_onboarding.get(
                            "provider_id"
                        ),
                        resolved_onboarding.get(
                            "branch_id"
                        ),
                    )
        except Exception:

            logger.exception(
                (
                    "Telegram callback "
                    "processing failed."
                )
            )

            await (
                telegram_client
                .send_message(
                    chat_id=chat_id,
                    text=(
                        "حصلت مشكلة أثناء تنفيذ "
                        "الاختيار. حاولي تاني."
                    ),
                )
            )

        return {
            "ok": True,
        }

    # ========================================================
    # TEXT MESSAGE
    # ========================================================

    message = (
        update.message
    )

    if (
        message is None
        or message.from_user is None
    ):

        return {
            "ok": True,
        }

    if message.from_user.is_bot:

        return {
            "ok": True,
        }

    chat_id = (
        message.chat.id
    )

    user_id = (
        message.from_user.id
    )

    text = str(
        message.text
        or ""
    ).strip()

    if not text:

        await (
            telegram_client
            .send_message(
                chat_id=chat_id,
                text=(
                    "دلوقتي أقدر أتعامل مع "
                    "الرسائل النصية بس."
                ),
            )
        )

        return {
            "ok": True,
        }

    session_id = (
        build_telegram_session_id(
            chat_id=chat_id,
            user_id=user_id,
        )
    )

    public_thread_id = (
        build_public_thread_id(
            session_id=session_id
        )
    )

    public_config = (
        _public_config(
            thread_id=public_thread_id,
            catalog_service=(
                catalog_service
            ),
        )
    )

    try:

        # ====================================================
        # /START /RESTART
        # ====================================================

        if text.lower() in {
            "/start",
            "/restart",
        }:

            _clear_pending_request(
                session_id
            )

            _clear_provider_selection_fresh(
                session_id
            )

            current_onboarding = (
                await _public_state(
                    graph=public_graph,
                    config=public_config,
                )
            )

            tenant_key = str(
                current_onboarding.get(
                    "tenant_key"
                )
                or ""
            ).strip()

            if tenant_key:

                current_booking_config = (
                    _booking_config(
                        tenant_key=(
                            tenant_key
                        ),
                        session_id=(
                            session_id
                        ),
                    )
                )

                current_booking_state = (
                    await _booking_state(
                        graph=booking_graph,
                        config=(
                            current_booking_config
                        ),
                    )
                )

                if (
                    current_booking_state.get(
                        "operation_status"
                    )
                    == "active"
                ):

                    await (
                        _save_abandoned_booking_state(
                            graph=booking_graph,
                            config=(
                                current_booking_config
                            ),
                            state=(
                                current_booking_state
                            ),
                            reason=(
                                "user_restart"
                            ),
                        )
                    )

            result = (
                await _start_onboarding(
                    graph=public_graph,
                    session_id=session_id,
                    config=public_config,
                )
            )

            await _send_result(
                telegram_client=(
                    telegram_client
                ),
                chat_id=chat_id,
                result=result,
            )

            return {
                "ok": True,
            }

        # ====================================================
        # READ ONBOARDING
        # ====================================================

        onboarding = (
            await _public_state(
                graph=public_graph,
                config=public_config,
            )
        )

        onboarding_completed = bool(
            onboarding.get(
                "onboarding_completed",
                False,
            )
        )

        greeting_reply = (
            _greeting_reply(
                text
            )
        )

        # ====================================================
        # NO ONBOARDING YET
        # ====================================================

        if not onboarding:

            if _message_starts_operation(
                text
            ):

                _remember_pending_request(
                    session_id,
                    text,
                )

            if (
                greeting_reply
                is not None
            ):

                await (
                    telegram_client
                    .send_message(
                        chat_id=chat_id,
                        text=(
                            greeting_reply
                        ),
                    )
                )

            result = (
                await _start_onboarding(
                    graph=public_graph,
                    session_id=session_id,
                    config=public_config,
                )
            )

            await _send_result(
                telegram_client=(
                    telegram_client
                ),
                chat_id=chat_id,
                result=result,
            )

            return {
                "ok": True,
            }

        # ====================================================
        # STILL SELECTING PROVIDER / BRANCH
        # ====================================================

        if not onboarding_completed:

            if _message_starts_operation(
                text
            ):

                _remember_pending_request(
                    session_id,
                    text,
                )

            if (
                greeting_reply
                is not None
            ):

                await (
                    telegram_client
                    .send_message(
                        chat_id=chat_id,
                        text=(
                            greeting_reply
                        ),
                    )
                )

            await _send_result(
                telegram_client=(
                    telegram_client
                ),
                chat_id=chat_id,
                result=onboarding,
            )

            return {
                "ok": True,
            }

        # ====================================================
        # ONBOARDING COMPLETE
        # ====================================================

        tenant_key = str(
            onboarding.get(
                "tenant_key"
            )
            or ""
        ).strip()

        provider_id = str(
            onboarding.get(
                "provider_id"
            )
            or ""
        ).strip()

        branch_id = str(
            onboarding.get(
                "branch_id"
            )
            or ""
        ).strip()

        if (
            not tenant_key
            or not provider_id
            or not branch_id
        ):

            if _message_starts_operation(
                text
            ):

                _remember_pending_request(
                    session_id,
                    text,
                )

            _clear_provider_selection_fresh(
                session_id
            )

            result = (
                await _start_onboarding(
                    graph=public_graph,
                    session_id=session_id,
                    config=public_config,
                )
            )

            await _send_result(
                telegram_client=(
                    telegram_client
                ),
                chat_id=chat_id,
                result=result,
            )

            return {
                "ok": True,
            }

        # ====================================================
        # CURRENT BOOKING STATE
        # ====================================================

        booking_config = (
            _booking_config(
                tenant_key=tenant_key,
                session_id=session_id,
            )
        )

        saved_booking_state = (
            await _booking_state(
                graph=booking_graph,
                config=booking_config,
            )
        )

        operation_status = str(
            saved_booking_state.get(
                "operation_status"
            )
            or ""
        ).strip()

        fresh_provider_authorized = False

        if (
            _message_starts_operation(
                text
            )
            and operation_status
            != "active"
        ):

            fresh_provider_authorized = (
                _consume_provider_selection_fresh(
                    session_id
                )
            )

            if fresh_provider_authorized:

                logger.info(
                    (
                        "telegram_fresh_provider_consumed "
                        "session_id=%s "
                        "operation=%s"
                    ),
                    session_id,
                    _requested_operation(
                        text
                    ),
                )

            else:

                _remember_pending_request(
                    session_id,
                    text,
                )

                _clear_provider_selection_fresh(
                    session_id
                )

                logger.info(
                    (
                        "telegram_new_operation_requires_provider "
                        "session_id=%s "
                        "operation=%s"
                    ),
                    session_id,
                    _requested_operation(
                        text
                    ),
                )

                restart_result = (
                    await _start_onboarding(
                        graph=public_graph,
                        session_id=session_id,
                        config=public_config,
                    )
                )

                await _send_result(
                    telegram_client=(
                        telegram_client
                    ),
                    chat_id=chat_id,
                    result=restart_result,
                )

                return {
                    "ok": True,
                }

        restart_reason = None

        if not fresh_provider_authorized:

            restart_reason = (
                public_restart_reason(
                    saved_booking_state,
                    text,
                )
            )


        if restart_reason is not None:

            if _message_starts_operation(
                text
            ):

                _remember_pending_request(
                    session_id,
                    text,
                )

            # Only ACTIVE operations may be marked
            # abandoned.
            if (
                saved_booking_state.get(
                    "operation_status"
                )
                == "active"
            ):

                await (
                    _save_abandoned_booking_state(
                        graph=booking_graph,
                        config=booking_config,
                        state=(
                            saved_booking_state
                        ),
                        reason=(
                            restart_reason
                        ),
                    )
                )

            _clear_provider_selection_fresh(
                session_id
            )

            if (
                greeting_reply
                is not None
            ):

                await (
                    telegram_client
                    .send_message(
                        chat_id=chat_id,
                        text=(
                            greeting_reply
                        ),
                    )
                )

            restart_result = (
                await _start_onboarding(
                    graph=public_graph,
                    session_id=session_id,
                    config=public_config,
                )
            )

            await _send_result(
                telegram_client=(
                    telegram_client
                ),
                chat_id=chat_id,
                result=restart_result,
            )

            return {
                "ok": True,
            }

        # ====================================================
        # BOOKING GRAPH HANDOFF
        # ====================================================

        booking_result = (
            await _invoke_booking_turn(
                graph=booking_graph,
                onboarding=onboarding,
                session_id=session_id,
                text=text,
            )
        )

        await _send_result(
            telegram_client=(
                telegram_client
            ),
            chat_id=chat_id,
            result=booking_result,
        )



        if (
            _should_restart_public_onboarding(
                booking_result
            )
        ):

            try:

                _clear_pending_request(
                    session_id
                )

                _clear_provider_selection_fresh(
                    session_id
                )

                restart_result = (
                    await _start_onboarding(
                        graph=public_graph,
                        session_id=session_id,
                        config=public_config,
                    )
                )

                await _send_result(
                    telegram_client=(
                        telegram_client
                    ),
                    chat_id=chat_id,
                    result=restart_result,
                )

            except Exception:

                logger.exception(
                    (
                        "Telegram post-operation "
                        "onboarding reset failed."
                    )
                )

    except Exception:

        logger.exception(
            (
                "Telegram message "
                "processing failed."
            )
        )

        await (
            telegram_client
            .send_message(
                chat_id=chat_id,
                text=(
                    "حصلت مشكلة مؤقتة في المساعد. "
                    "حاولي تاني بعد شوية."
                ),
            )
        )

    return {
        "ok": True,
    }