from __future__ import annotations

import logging
import re
import time

from typing import Any

import httpx

from mcp_server.config import (
    get_mcp_settings,
)


logger = logging.getLogger(
    "uvicorn.error"
)


TENANT_PATTERN = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._-]{0,63}$"
)


class BackendClient:
    """
    Persistent HTTP client used by MCP tools.

    Architecture:

        MCP Tool
            ↓
        BackendClient
            ↓
        FastAPI Backend
            ↓
        SQL Server

    Important:

    - HTTP connection pooling is shared.
    - Tenant identity is NOT stored globally.
    - tenant_id is supplied per request.
    - The AsyncClient is created once during
      MCP startup and closed during shutdown.
    """

    def __init__(
        self,
    ) -> None:

        settings = (
            get_mcp_settings()
        )

        self.base_url = (
            settings.backend_base_url.rstrip(
                "/"
            )
        )

        self.timeout = (
            settings.request_timeout
        )

        self._client: (
            httpx.AsyncClient
            | None
        ) = None

    # ========================================================
    # Lifecycle
    # ========================================================

    async def start(
        self,
    ) -> None:

        if self._client is not None:
            return

        timeout = (
            httpx.Timeout(
                self.timeout,
                connect=5.0,
            )
        )

        self._client = (
            httpx.AsyncClient(
                timeout=timeout,
                trust_env=False,
            )
        )

        logger.info(
            "backend_http_client_started"
        )

    async def warmup(
        self,
    ) -> bool:
        """
        Warm the persistent Backend HTTP connection
        using the lightweight liveness endpoint.

        Best-effort only:
        MCP startup must not fail if the Backend
        is temporarily unavailable.
        """

        client = (
            self._require_client()
        )

        started = (
            time.perf_counter()
        )

        url = (
            f"{self.base_url}"
            "/health/live"
        )

        try:

            response = await (
                client.get(
                    url,
                )
            )

            response.raise_for_status()

            elapsed_ms = (
                time.perf_counter()
                - started
            ) * 1000

            logger.info(
                "backend_http_warmup "
                "elapsed_ms=%.2f "
                "status=success",
                elapsed_ms,
            )

            return True

        except httpx.HTTPError as exc:

            elapsed_ms = (
                time.perf_counter()
                - started
            ) * 1000

            logger.warning(
                "backend_http_warmup "
                "elapsed_ms=%.2f "
                "status=failed "
                "error_type=%s",
                elapsed_ms,
                type(exc).__name__,
            )

            return False    

    async def close(
        self,
    ) -> None:

        client = (
            self._client
        )

        if client is None:
            return

        self._client = None

        await (
            client.aclose()
        )

        logger.info(
            "backend_http_client_closed"
        )

    # ========================================================
    # Client access
    # ========================================================

    def _require_client(
        self,
    ) -> httpx.AsyncClient:

        client = (
            self._client
        )

        if client is None:

            raise RuntimeError(
                "BackendClient has not been started."
            )

        return client

    # ========================================================
    # Tenant validation
    # ========================================================

    @staticmethod
    def _validate_tenant_id(
        tenant_id: str,
    ) -> str:

        value = (
            str(
                tenant_id
            )
            .strip()
        )

        if not TENANT_PATTERN.fullmatch(
            value
        ):

            raise RuntimeError(
                "Invalid tenant identity "
                "for Backend request."
            )

        return value

    # ========================================================
    # Headers
    # ========================================================

    def _build_headers(
        self,
        *,
        tenant_id: str,
        idempotency_key: (
            str
            | None
        ) = None,
    ) -> dict[str, str]:

        validated_tenant = (
            self._validate_tenant_id(
                tenant_id
            )
        )

        headers = {
            "X-Tenant-ID":
                validated_tenant,

            "Accept":
                "application/json",
        }

        if idempotency_key:

            headers[
                "Idempotency-Key"
            ] = (
                idempotency_key
            )

        return headers

    # ========================================================
    # Request
    # ========================================================

    async def request(
        self,
        *,
        tenant_id: str,
        method: str,
        path: str,
        json: (
            dict[str, Any]
            | None
        ) = None,
        params: (
            dict[str, Any]
            | None
        ) = None,
        idempotency_key: (
            str
            | None
        ) = None,
    ) -> (
        dict[str, Any]
        | list[Any]
    ):

        client = (
            self._require_client()
        )

        url = (
            f"{self.base_url}"
            f"{path}"
        )

        total_started_at = (
            time.perf_counter()
        )

        # ====================================================
        # Headers
        # ====================================================

        headers_started_at = (
            time.perf_counter()
        )

        headers = (
            self._build_headers(
                tenant_id=tenant_id,
                idempotency_key=(
                    idempotency_key
                ),
            )
        )

        headers_ms = (
            (
                time.perf_counter()
                - headers_started_at
            )
            * 1000
        )

        # ====================================================
        # HTTP
        # ====================================================

        request_started_at = (
            time.perf_counter()
        )

        try:

            response = await (
                client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    params=params,
                )
            )

        except httpx.ConnectError as exc:

            raise RuntimeError(
                "Cannot connect to Backend at "
                f"{url}"
            ) from exc

        except httpx.ReadTimeout as exc:

            raise RuntimeError(
                "Backend timed out while "
                "processing "
                f"{method} {path}"
            ) from exc

        except httpx.TimeoutException as exc:

            raise RuntimeError(
                "Backend request timed out for "
                f"{method} {path}"
            ) from exc

        except httpx.HTTPError as exc:

            raise RuntimeError(
                "HTTP communication error while "
                "calling "
                f"{method} {path}: {exc}"
            ) from exc

        request_ms = (
            (
                time.perf_counter()
                - request_started_at
            )
            * 1000
        )

        # ====================================================
        # Success
        # ====================================================

        if response.is_success:

            if not response.content:

                total_ms = (
                    (
                        time.perf_counter()
                        - total_started_at
                    )
                    * 1000
                )

                logger.info(
                    "backend_http_timing "
                    "method=%s "
                    "path=%s "
                    "headers_ms=%.2f "
                    "request_ms=%.2f "
                    "json_ms=0.00 "
                    "total_ms=%.2f "
                    "status_code=%d",
                    method,
                    path,
                    headers_ms,
                    request_ms,
                    total_ms,
                    response.status_code,
                )

                return {
                    "ok": True,
                }

            # ================================================
            # JSON parsing
            # ================================================

            json_started_at = (
                time.perf_counter()
            )

            try:

                payload = (
                    response.json()
                )

            except ValueError as exc:

                raise RuntimeError(
                    "Backend returned successful "
                    "response with invalid JSON."
                ) from exc

            json_ms = (
                (
                    time.perf_counter()
                    - json_started_at
                )
                * 1000
            )

            total_ms = (
                (
                    time.perf_counter()
                    - total_started_at
                )
                * 1000
            )

            logger.info(
                "backend_http_timing "
                "method=%s "
                "path=%s "
                "headers_ms=%.2f "
                "request_ms=%.2f "
                "json_ms=%.2f "
                "total_ms=%.2f "
                "status_code=%d",
                method,
                path,
                headers_ms,
                request_ms,
                json_ms,
                total_ms,
                response.status_code,
            )

            return payload

        # ====================================================
        # Backend error
        # ====================================================

        self._raise_backend_error(
            response
        )

    # ========================================================
    # Backend errors
    # ========================================================

    @staticmethod
    def _raise_backend_error(
        response: httpx.Response,
    ) -> None:

        try:

            payload = (
                response.json()
            )

        except ValueError:

            payload = {}

        detail = (
            payload.get(
                "detail",
                {},
            )
        )

        if isinstance(
            detail,
            dict,
        ):

            code = (
                detail.get(
                    "code",
                    "BACKEND_ERROR",
                )
            )

            message = (
                detail.get(
                    "message",
                    "Backend request failed.",
                )
            )

        else:

            code = (
                "BACKEND_ERROR"
            )

            message = (
                str(
                    detail
                )
            )

        raise RuntimeError(
            f"{code}: {message} "
            f"(HTTP {response.status_code})"
        )


# ============================================================
# Shared process-level client
#
# Connection pool is shared.
# Tenant identity remains request-scoped.
# ============================================================

backend_client = (
    BackendClient()
)