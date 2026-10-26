"""Log-safety helpers for the Voice Gateway.

Caller speech, provider message contents, provider error bodies and
URLs carrying credentials must never reach the logs, at any level.

Exception messages are the subtle case: they are often provider- or
caller-controlled text. A websockets ``InvalidURI`` message contains the
full connection URL (including the Hamsa ``api_key`` query parameter), a
close reason is whatever the provider sent, and an exception raised while
preparing a reply may quote the reply. ``SafeExceptionFilter`` therefore
keeps tracebacks useful (exception types, files, line numbers, function
names) but drops every exception message.

How it is used:

* Transcript and provider paths log explicitly with ``exception_fields()``
  (class, code, source location) and never attach a traceback.
* ``SafeExceptionFilter`` is a backstop on the Voice Gateway's own loggers
  and on ``uvicorn.error`` (installed by voice_gateway.main) for any remaining
  ``logger.exception`` call. It only rewrites exception info: it does NOT
  sanitize ``record.msg`` / ``record.args`` (never pass raw values as log
  arguments), it is not inherited by child loggers (call
  ``install_log_safety`` on every new logger), and it is process-local. It
  does not affect other third-party loggers such as asyncio, Gunicorn, httpx
  or provider SDKs.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import traceback
from collections.abc import Mapping
from typing import Any

# Provider JSON codes such as "UNAUTHORIZED" or "RATE_LIMITED": uppercase
# letters and underscores only, no digits (a digit run could be an ID).
_SAFE_CODE_TEXT = re.compile(r"^[A-Z][A-Z_]{0,31}$")
_SAFE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
# Large enough for HTTP, WebSocket close and provider codes, too small to
# hold a national ID or phone number.
_MAX_NUMERIC_CODE = 99_999
_MAX_FIELDS = 20

OMITTED = "<message omitted>"
TRACEBACK_OMITTED = "Traceback omitted (log safety could not format it)"


def _type_name(value: Any) -> str:
    try:
        return type(value).__name__
    except Exception:
        return "unknown"


def _safe_getattr(obj: Any, name: str) -> Any:
    """getattr that never raises (properties may raise anything)."""

    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def safe_numeric_code(value: Any) -> str:
    """An integer code in 0..99999, or "none". Used for exception attributes."""

    if isinstance(value, int) and not isinstance(value, bool):
        return str(value) if 0 <= value <= _MAX_NUMERIC_CODE else "none"
    return "none"


def safe_code(value: Any) -> str:
    """A provider JSON code, or "none".

    Accepts an integer in 0..99999, a string of at most 5 ASCII digits, or a
    short uppercase/underscore token without digits. Anything else (free
    text, keys, long numbers, mixed-case words) becomes "none".

    Known limit: an all-uppercase Latin word (e.g. "AHMED") is accepted. This
    only affects log text. Replace the token rule with an allowlist once the
    provider's documented codes are verified.
    """

    try:
        numeric = safe_numeric_code(value)
        if numeric != "none":
            return numeric
        if isinstance(value, str):
            value = value.strip()
            if value.isascii() and value.isdigit() and len(value) <= 5:
                return value
            if _SAFE_CODE_TEXT.fullmatch(value):
                return value
    except Exception:
        pass
    return "none"


def describe_message(message: Any) -> str:
    """The shape of a provider message (kind, type, size, field names), never its values."""

    try:
        if isinstance(message, Mapping):
            fields = sorted(
                key if isinstance(key, str) and _SAFE_FIELD.fullmatch(key) else "?"
                for key in message
            )
            shown = ",".join(fields[:_MAX_FIELDS]) or "-"
            if len(fields) > _MAX_FIELDS:
                shown += ",..."
            return (
                f"kind=object type={safe_code(message.get('type'))} "
                f"fields={shown}"
            )

        if isinstance(message, (list, tuple)):
            return f"kind=array items={len(message)}"

        if message is None or isinstance(message, bool):
            return f"kind={_type_name(message)}"

        # Strings, bytes and numbers: size only (a bare number may be a national ID).
        size = len(message) if isinstance(message, (str, bytes)) else len(str(message))
        return f"kind={_type_name(message)} chars={size}"
    except Exception:
        return f"kind={_type_name(message)}"


def describe_error(error: Any) -> str:
    """Type and safe integer code of a provider error object or exception.

    Only integer codes are reported (status_code, code, error_code,
    response.status_code, or a websockets close frame's code). Never raises.
    """

    code = "none"
    try:
        # websockets ConnectionClosed: use the received close frame and never
        # touch its deprecated ``code`` property.
        try:
            has_close_frames = "rcvd" in vars(error)
        except TypeError:  # no instance __dict__
            has_close_frames = False

        if has_close_frames:
            code = safe_numeric_code(_safe_getattr(_safe_getattr(error, "rcvd"), "code"))
        else:
            for attribute in ("status_code", "code", "error_code"):
                code = safe_numeric_code(_safe_getattr(error, attribute))
                if code != "none":
                    break

        if code == "none":
            response = _safe_getattr(error, "response")
            code = safe_numeric_code(_safe_getattr(response, "status_code"))
    except Exception:
        code = "none"

    return f"error_type={_type_name(error)} error_code={code}"


def exception_cause_type(exc: BaseException) -> str | None:
    """Class name of the exception's cause (or implicit context), if any."""

    try:
        cause = exc.__cause__
        if cause is None and not exc.__suppress_context__:
            cause = exc.__context__
        return _type_name(cause) if cause is not None else None
    except Exception:
        return None


def exception_origin(exc: BaseException, depth: int = 3) -> str:
    """Innermost ``depth`` frames as ``file.py:line``, innermost first."""

    try:
        frames = traceback.extract_tb(exc.__traceback__)[-depth:]
        if not frames:
            return "unknown"
        return "<".join(
            f"{os.path.basename(frame.filename)}:{frame.lineno}"
            for frame in reversed(frames)
        )
    except Exception:
        return "unknown"


def exception_fields(exc: BaseException | None = None) -> str:
    """Safe diagnostics for an exception: class, code, source location and
    the class of its cause.

    Defaults to the exception currently being handled. Never includes an
    exception message or a traceback, and never raises: a logging call must
    not interrupt the handler it is reporting from.
    """

    try:
        if exc is None:
            exc = sys.exc_info()[1]
        if exc is None:
            return "error_type=none"
        fields = f"{describe_error(exc)} error_origin={exception_origin(exc)}"
        cause = exception_cause_type(exc)
        if cause:
            fields += f" cause_type={cause}"
        return fields
    except Exception:
        return f"error_type={_type_name(exc)} error_code=none error_origin=unknown"


def safe_traceback(exc: BaseException | None) -> str:
    """A traceback with every exception message replaced by OMITTED."""

    try:
        chain: list[BaseException] = []
        seen: set[int] = set()
        current = exc
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            chain.append(current)
            if current.__cause__ is not None:
                current = current.__cause__
            elif current.__suppress_context__:
                current = None
            else:
                current = current.__context__

        lines: list[str] = []
        for index, item in enumerate(reversed(chain)):
            if index:
                lines.append("")
                lines.append("The above exception led to another exception:")
                lines.append("")
            lines.append("Traceback (most recent call last; messages omitted):")
            for frame in traceback.extract_tb(item.__traceback__):
                lines.append(
                    f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'
                )
            exc_type = type(item)
            lines.append(f"{exc_type.__module__}.{exc_type.__qualname__}: {OMITTED}")

        return "\n".join(lines)
    except Exception:
        return TRACEBACK_OMITTED


class SafeExceptionFilter(logging.Filter):
    """Replace a record's exception info with a message-free traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.exc_info:
                exc = record.exc_info[1]
                record.exc_text = safe_traceback(exc) if exc is not None else None
                record.exc_info = None
        except Exception:
            record.exc_text = TRACEBACK_OMITTED
            record.exc_info = None
        return True


def install_log_safety(logger: logging.Logger) -> logging.Logger:
    """Attach SafeExceptionFilter to ``logger`` once and return it."""

    if not any(isinstance(f, SafeExceptionFilter) for f in logger.filters):
        logger.addFilter(SafeExceptionFilter())
    return logger
