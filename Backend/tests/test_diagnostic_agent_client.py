import json

import httpx
import pytest

from app.integrations.diagnostic_agent_client import (
    DiagnosticAgentClient,
    DiagnosticAgentRequestError,
    DiagnosticAgentResponseError,
    DiagnosticAgentUnavailableError,
)


# ============================================================
# SUCCESS
# ============================================================


@pytest.mark.asyncio
async def test_radiology_success():

    async def handler(
        request: httpx.Request,
    ):

        assert (
            request.url.path
            == "/v1/radiology/analyze"
        )

        return httpx.Response(
            200,
            json={
                "modality":
                    "brain_mri",

                "classification":
                    "pituitary",

                "probabilities": {
                    "glioma": 0.02,
                    "meningioma": 0.09,
                    "notumor": 0.02,
                    "pituitary": 0.87,
                },

                "confidence":
                    0.87,

                "inference_latency_ms":
                    123.4,

                "model_name":
                    "test-model",

                "model_version":
                    "v1",

                "limitations": [
                    "Decision-support only."
                ],
            },
        )

    transport = httpx.MockTransport(
        handler
    )

    async with httpx.AsyncClient(
        transport=transport,
    ) as http_client:

        client = DiagnosticAgentClient(
            base_url="http://diagnostics",
            http_client=http_client,
        )

        result = await (
            client.analyze_radiology(
                image_bytes=b"image",
                filename="brain.jpg",
                content_type="image/jpeg",
                modality="brain_mri",
            )
        )

    assert (
        result.modality
        == "brain_mri"
    )

    assert (
        result.classification
        == "pituitary"
    )

    assert (
        result.confidence
        == pytest.approx(
            0.87
        )
    )


# ============================================================
# DIAGNOSTIC AGENT REJECTION
# ============================================================


@pytest.mark.asyncio
async def test_radiology_request_error():

    async def handler(
        request: httpx.Request,
    ):

        return httpx.Response(
            400,
            json={
                "detail": {
                    "code":
                        "UNSUPPORTED_RADIOLOGY_MODALITY"
                }
            },
        )

    transport = httpx.MockTransport(
        handler
    )

    async with httpx.AsyncClient(
        transport=transport,
    ) as http_client:

        client = DiagnosticAgentClient(
            base_url="http://diagnostics",
            http_client=http_client,
        )

        with pytest.raises(
            DiagnosticAgentRequestError,
            match=(
                "UNSUPPORTED_RADIOLOGY_MODALITY"
            ),
        ):

            await (
                client.analyze_radiology(
                    image_bytes=b"image",
                    filename="scan.jpg",
                    content_type="image/jpeg",
                    modality="pet_scan",
                )
            )


# ============================================================
# INVALID RESPONSE
# ============================================================


@pytest.mark.asyncio
async def test_invalid_response_contract():

    async def handler(
        request: httpx.Request,
    ):

        return httpx.Response(
            200,
            json={
                "unexpected":
                    "payload"
            },
        )

    transport = httpx.MockTransport(
        handler
    )

    async with httpx.AsyncClient(
        transport=transport,
    ) as http_client:

        client = DiagnosticAgentClient(
            base_url="http://diagnostics",
            http_client=http_client,
        )

        with pytest.raises(
            DiagnosticAgentResponseError
        ):

            await (
                client.analyze_radiology(
                    image_bytes=b"image",
                    filename="scan.jpg",
                    content_type="image/jpeg",
                    modality="brain_mri",
                )
            )


# ============================================================
# NETWORK FAILURE
# ============================================================


@pytest.mark.asyncio
async def test_network_failure():

    async def handler(
        request: httpx.Request,
    ):

        raise httpx.ConnectError(
            "connection failed",
            request=request,
        )

    transport = httpx.MockTransport(
        handler
    )

    async with httpx.AsyncClient(
        transport=transport,
    ) as http_client:

        client = DiagnosticAgentClient(
            base_url="http://diagnostics",
            http_client=http_client,
        )

        with pytest.raises(
            DiagnosticAgentUnavailableError
        ):

            await (
                client.analyze_radiology(
                    image_bytes=b"image",
                    filename="scan.jpg",
                    content_type="image/jpeg",
                    modality="brain_mri",
                )
            )

@pytest.mark.asyncio
async def test_analyze_pathology_success():

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:

        assert (
            request.url.path
            == "/v1/pathology/analyze"
        )

        return httpx.Response(
            status_code=200,
            json={
                "schema_version":
                    "1.0",

                "document_type":
                    "cbc",

                "unreadable_fields":
                    [],

                "results": [
                    {
                        "result_index":
                            0,

                        "panel":
                            "cbc",

                        "raw_name":
                            "Hemoglobin",

                        "canonical_name":
                            "hemoglobin",

                        "value":
                            12.0,

                        "unit":
                            "g/dL",

                        "reference_min":
                            12.0,

                        "reference_max":
                            16.0,

                        "reference_text":
                            None,

                        "flag":
                            "normal",

                        "mapping_status":
                            "mapped",
                    }
                ],
            },
        )

    transport = (
        httpx.MockTransport(
            handler
        )
    )

    http_client = (
        httpx.AsyncClient(
            transport=transport
        )
    )

    client = DiagnosticAgentClient(
        base_url=(
            "http://diagnostic-agent"
        ),
        http_client=http_client,
    )

    try:

        result = await (
            client.analyze_pathology(
                image_bytes=(
                    b"fake-lab-image"
                ),
                filename=(
                    "cbc.png"
                ),
                content_type=(
                    "image/png"
                ),
            )
        )

    finally:

        await http_client.aclose()

    assert (
        result.schema_version
        == "1.0"
    )

    assert (
        result.document_type
        == "cbc"
    )

    assert (
        len(
            result.results
        )
        == 1
    )

    assert (
        result.results[0]
        .canonical_name
        == "hemoglobin"
    )

    assert (
        result.results[0]
        .value
        == 12.0
    )

    assert (
        result.results[0]
        .flag
        == "normal"
    )            