from __future__ import annotations

import os

from typing import Any, Literal

import httpx

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
)


# ============================================================
# RESPONSE CONTRACT
# ============================================================


class RadiologyAgentResponse(
    BaseModel
):

    modality: str

    classification: str

    probabilities: dict[
        str,
        float,
    ]

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    inference_latency_ms: float = Field(
        ge=0.0,
    )

    model_name: str

    model_version: str

    limitations: list[str]

class PathologyResultResponse(
    BaseModel
):

    result_index: int = Field(
        ge=0,
    )

    panel: str | None = None

    raw_name: str

    canonical_name: str | None = None

    value: float | None = None

    unit: str | None = None

    reference_min: float | None = None

    reference_max: float | None = None

    reference_text: str | None = None

    flag: str

    mapping_status: str


class PathologyAgentResponse(
    BaseModel
):

    schema_version: str

    document_type: str | None = None

    unreadable_fields: list[str]

    results: list[
        PathologyResultResponse
    ]


class ImageTypeClassificationResponse(BaseModel):
    category: Literal[
        "pathology",
        "chest_xray",
        "brain_mri",
        "kidney_ct",
        "other",
    ]
    confidence: float = Field(ge=0.0, le=1.0)

# ============================================================
# ERRORS
# ============================================================


class DiagnosticAgentClientError(
    RuntimeError
):
    """Base Diagnostic Agent client error."""


class DiagnosticAgentUnavailableError(
    DiagnosticAgentClientError
):
    """Diagnostic Agent could not be reached."""


class DiagnosticAgentRequestError(
    DiagnosticAgentClientError
):
    """
    Diagnostic Agent rejected the request.
    """


class DiagnosticAgentResponseError(
    DiagnosticAgentClientError
):
    """
    Diagnostic Agent returned an invalid response.
    """


# ============================================================
# CLIENT
# ============================================================


class DiagnosticAgentClient:

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        http_client:
            httpx.AsyncClient
            | None = None,
    ) -> None:

        self.base_url = (
            base_url
            or os.getenv(
                "DIAGNOSTIC_AGENT_URL",
                "http://127.0.0.1:9100",
            )
        ).rstrip("/")

        resolved_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(
                os.getenv(
                    "DIAGNOSTIC_AGENT_TIMEOUT_SECONDS",
                    "15",
                )
            )
        )

        if resolved_timeout <= 0:

            raise ValueError(
                "Diagnostic Agent timeout "
                "must be greater than zero."
            )

        self._owns_client = (
            http_client is None
        )

        self._client = (
            http_client
            or httpx.AsyncClient(
                timeout=httpx.Timeout(
                    resolved_timeout,
                    connect=3.0,
                ),
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=60.0,
                ),
            )
        )

    # ========================================================
    # IMAGE TYPE CLASSIFICATION
    # ========================================================

    async def classify_image(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> ImageTypeClassificationResponse:
        if not image_bytes:
            raise ValueError("image_bytes cannot be empty.")

        try:
            response = await self._client.post(
                f"{self.base_url}/v1/classify-image",
                files={
                    "file": (filename, image_bytes, content_type),
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise DiagnosticAgentUnavailableError(
                "Diagnostic Agent is unavailable."
            ) from exc

        if response.status_code >= 400:
            code = self._extract_error_code(response)
            raise DiagnosticAgentRequestError(
                code or "Diagnostic Agent image classification failed."
            )

        try:
            return ImageTypeClassificationResponse.model_validate(
                response.json()
            )
        except (ValueError, ValidationError) as exc:
            raise DiagnosticAgentResponseError(
                "Diagnostic Agent returned an invalid image classification."
            ) from exc

    # ========================================================
    # RADIOLOGY
    # ========================================================

    async def analyze_radiology(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        content_type: str,
        modality: str,
    ) -> RadiologyAgentResponse:

        if not image_bytes:

            raise ValueError(
                "image_bytes cannot be empty."
            )

        modality = (
            modality.strip()
        )

        if not modality:

            raise ValueError(
                "modality cannot be empty."
            )

        try:

            response = await (
                self._client.post(
                    (
                        f"{self.base_url}"
                        "/v1/radiology/analyze"
                    ),
                    data={
                        "modality":
                            modality,
                    },
                    files={
                        "file": (
                            filename,
                            image_bytes,
                            content_type,
                        ),
                    },
                )
            )

        except (
            httpx.TimeoutException,
            httpx.NetworkError,
        ) as exc:

            raise (
                DiagnosticAgentUnavailableError(
                    "Diagnostic Agent "
                    "is unavailable."
                )
            ) from exc

        # ----------------------------------------------------
        # Request rejected by Diagnostic Agent.
        # ----------------------------------------------------

        if (
            response.status_code
            >= 400
        ):

            code = (
                self._extract_error_code(
                    response
                )
            )

            raise (
                DiagnosticAgentRequestError(
                    code
                    or
                    (
                        "Diagnostic Agent "
                        "request failed."
                    )
                )
            )

        # ----------------------------------------------------
        # Stable response contract.
        # ----------------------------------------------------

        try:

            payload: Any = (
                response.json()
            )

            return (
                RadiologyAgentResponse
                .model_validate(
                    payload
                )
            )

        except (
            ValueError,
            ValidationError,
        ) as exc:

            raise (
                DiagnosticAgentResponseError(
                    "Diagnostic Agent returned "
                    "an invalid response."
                )
            ) from exc

    # ========================================================
    # PATHOLOGY
    # ========================================================

    async def analyze_pathology(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> PathologyAgentResponse:

        if not image_bytes:

            raise ValueError(
                "image_bytes cannot be empty."
            )

        try:

            response = await (
                self._client.post(
                    (
                        f"{self.base_url}"
                        "/v1/pathology/analyze"
                    ),
                    files={
                        "file": (
                            filename,
                            image_bytes,
                            content_type,
                        ),
                    },
                )
            )

        except (
            httpx.TimeoutException,
            httpx.NetworkError,
        ) as exc:

            raise (
                DiagnosticAgentUnavailableError(
                    "Diagnostic Agent "
                    "is unavailable."
                )
            ) from exc

        if (
            response.status_code
            >= 400
        ):

            code = (
                self._extract_error_code(
                    response
                )
            )

            raise (
                DiagnosticAgentRequestError(
                    code
                    or
                    (
                        "Diagnostic Agent "
                        "request failed."
                    )
                )
            )

        try:

            payload: Any = (
                response.json()
            )

            return (
                PathologyAgentResponse
                .model_validate(
                    payload
                )
            )

        except (
            ValueError,
            ValidationError,
        ) as exc:

            raise (
                DiagnosticAgentResponseError(
                    "Diagnostic Agent returned "
                    "an invalid response."
                )
            ) from exc
    # ========================================================
    # ERROR EXTRACTION
    # ========================================================

    @staticmethod
    def _extract_error_code(
        response: httpx.Response,
    ) -> str | None:

        try:

            payload = (
                response.json()
            )

        except ValueError:

            return None

        if not isinstance(
            payload,
            dict,
        ):

            return None

        detail = (
            payload.get(
                "detail"
            )
        )

        if not isinstance(
            detail,
            dict,
        ):

            return None

        code = detail.get(
            "code"
        )

        if not isinstance(
            code,
            str,
        ):

            return None

        code = code.strip()

        return (
            code
            or None
        )

    # ========================================================
    # CLEANUP
    # ========================================================

    async def close(
        self,
    ) -> None:

        if self._owns_client:

            await (
                self._client.aclose()
            )
