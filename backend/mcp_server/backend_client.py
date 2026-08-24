import re

from typing import Any

import httpx

from mcp_server.config import (
    get_mcp_settings,
)


TENANT_PATTERN = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._-]{0,63}$"
)


class BackendClient:
    """
    Thin HTTP client used by MCP tools.

    Architecture:

        MCP Tool
            ↓
        BackendClient
            ↓
        FastAPI Backend
            ↓
        SQL Server

    Important:

    BackendClient is intentionally stateless
    with respect to tenant identity.

    tenant_id is supplied per request so
    concurrent requests from different tenants
    cannot overwrite each other's tenant state.
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
        idempotency_key: str | None = None,
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

        url = (
            f"{self.base_url}"
            f"{path}"
        )

        timeout = httpx.Timeout(
            self.timeout,
            connect=5.0,
        )

        try:

            async with (
                httpx.AsyncClient(
                    timeout=timeout,
                    trust_env=False,
                )
                as client
            ):

                response = (
                    await client.request(
                        method=method,

                        url=url,

                        headers=(
                            self._build_headers(
                                tenant_id=(
                                    tenant_id
                                ),

                                idempotency_key=(
                                    idempotency_key
                                ),
                            )
                        ),

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

        # ====================================================
        # Success
        # ====================================================

        if response.is_success:

            if not response.content:

                return {
                    "ok":
                        True,
                }

            try:

                return (
                    response.json()
                )

            except ValueError as exc:

                raise RuntimeError(
                    "Backend returned successful "
                    "response but it was not JSON "
                    f"for {method} {path}."
                ) from exc

        # ====================================================
        # Backend Error
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

        detail = payload.get(
            "detail",
            {},
        )

        if isinstance(
            detail,
            dict,
        ):

            code = detail.get(
                "code",
                "BACKEND_ERROR",
            )

            message = detail.get(
                "message",
                "Backend request failed.",
            )

        else:

            code = (
                "BACKEND_ERROR"
            )

            message = str(
                detail
            )

        raise RuntimeError(
            f"{code}: {message} "
            f"(HTTP {response.status_code})"
        )


# Safe global client:
#
# - base_url is immutable runtime configuration
# - timeout is immutable runtime configuration
# - tenant is NOT stored here

backend_client = BackendClient()