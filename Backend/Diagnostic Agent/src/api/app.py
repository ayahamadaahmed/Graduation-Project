from __future__ import annotations

import os
import tempfile
from pathlib import Path
import logging
from time import perf_counter

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
import asyncio
from pydantic import (
    BaseModel,
    Field,
)

from src.diagnostics.radiology.radiology_assessment import (
    RadiologyAssessmentBuilder,
)
from src.diagnostics.radiology.radiology_processor import (
    RadiologyModality,
    RadiologyProcessor,
    UnsupportedRadiologyModalityError,
)
from src.diagnostics.lab_image_extractor import (
    LabImageExtractor,
    OpenAILabVisionProvider,
)

from src.diagnostics.pathology_pipeline import (
    PathologyPipeline,
)

from src.diagnostics.pathology_persistence_contract import (
    PathologyPersistenceContractBuilder,
    PathologyPersistenceContractError,
)

# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="MedMind Diagnostic Agent",
    version="1.0.0",
)

logger = logging.getLogger("uvicorn.error")

# ============================================================
# CONFIG
# ============================================================

MAX_IMAGE_BYTES = int(
    os.getenv(
        "DIAGNOSTIC_MAX_IMAGE_BYTES",
        str(10 * 1024 * 1024),
    )
)

SUPPORTED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


# ============================================================
# SHARED PROCESSORS
#
# IMPORTANT:
# Load models once per Diagnostic Agent process.
# Do not construct them per request.
# ============================================================

radiology_processor = (
    RadiologyProcessor()
)

radiology_assessment_builder = (
    RadiologyAssessmentBuilder()
)

pathology_pipeline: PathologyPipeline | None = None

pathology_persistence_builder = (
    PathologyPersistenceContractBuilder()
)


def get_pathology_pipeline() -> PathologyPipeline:

    global pathology_pipeline

    if pathology_pipeline is None:

        vision_provider = (
            OpenAILabVisionProvider()
        )

        extractor = (
            LabImageExtractor(
                vision_provider
            )
        )

        pathology_pipeline = (
            PathologyPipeline(
                extractor=extractor
            )
        )

    return pathology_pipeline


@app.on_event("startup")
async def warm_up_radiology_models() -> None:
    """
    Warm radiology models once when the Diagnostic Agent starts.

    This avoids the first real patient request paying the
    TensorFlow first-predict initialization cost.
    """

    enabled = (
        os.getenv(
            "DIAGNOSTIC_RADIOLOGY_WARMUP_ENABLED",
            "1",
        )
        .strip()
        .lower()
    )

    if enabled in {
        "0",
        "false",
        "no",
        "off",
    }:
        app.state.radiology_warmup = {
            "enabled": False,
            "timings_ms": {},
            "total_ms": 0.0,
        }

        logger.info(
            "radiology_warmup_skipped enabled=false"
        )

        return

    started_at = perf_counter()

    timings_ms = await asyncio.to_thread(
        radiology_processor.warm_up
    )

    total_ms = (
        perf_counter() - started_at
    ) * 1000.0

    app.state.radiology_warmup = {
        "enabled": True,
        "timings_ms": timings_ms,
        "total_ms": total_ms,
    }

    logger.info(
        (
            "radiology_warmup_completed "
            "total_ms=%.2f "
            "chest_xray_ms=%.2f "
            "brain_mri_ms=%.2f "
            "kidney_ct_ms=%.2f"
        ),
        total_ms,
        timings_ms.get(
            "chest_xray",
            0.0,
        ),
        timings_ms.get(
            "brain_mri",
            0.0,
        ),
        timings_ms.get(
            "kidney_ct",
            0.0,
        ),
    )

# ============================================================
# RESPONSE SCHEMA
# ============================================================

class RadiologyAnalyzeResponse(
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


class PathologyAnalyzeResponse(
    BaseModel
):

    schema_version: str

    document_type: str | None = None

    unreadable_fields: list[str]

    results: list[
        PathologyResultResponse
    ]

# ============================================================
# HEALTH
# ============================================================

@app.get(
    "/health",
)
async def health():

    return {
        "status": "ok",
        "service":
            "medmind-diagnostic-agent",
    }


# ============================================================
# RADIOLOGY
# ============================================================

@app.post(
    "/v1/radiology/analyze",
    response_model=RadiologyAnalyzeResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_radiology(
    modality: str = Form(
        ...,
    ),
    file: UploadFile = File(
        ...,
    ),
) -> RadiologyAnalyzeResponse:

    # --------------------------------------------------------
    # Explicit modality only.
    # --------------------------------------------------------

    try:

        normalized_modality = (
            RadiologyModality(
                modality
                .strip()
                .lower()
            )
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "UNSUPPORTED_RADIOLOGY_MODALITY",

                "message":
                    (
                        "Supported modalities are "
                        "chest_xray, brain_mri, "
                        "kidney_ct."
                    ),
            },
        ) from exc

    # --------------------------------------------------------
    # Image type.
    # --------------------------------------------------------

    content_type = (
        file.content_type
        or ""
    ).strip().lower()

    suffix = (
        SUPPORTED_CONTENT_TYPES.get(
            content_type
        )
    )

    if suffix is None:

        raise HTTPException(
            status_code=(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
            ),
            detail={
                "code":
                    "UNSUPPORTED_DIAGNOSTIC_FILE_TYPE",

                "message":
                    (
                        "Only JPEG and PNG images "
                        "are supported."
                    ),
            },
        )

    # --------------------------------------------------------
    # Bounded read.
    # --------------------------------------------------------

    try:

        data = await file.read(
            MAX_IMAGE_BYTES + 1
        )

    finally:

        await file.close()

    if len(data) > MAX_IMAGE_BYTES:

        raise HTTPException(
            status_code=(
                status.HTTP_413_CONTENT_TOO_LARGE
            ),
            detail={
                "code":
                    "DIAGNOSTIC_FILE_TOO_LARGE",

                "message":
                    (
                        "The diagnostic image "
                        "exceeds the allowed size."
                    ),
            },
        )

    if not data:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "EMPTY_DIAGNOSTIC_FILE",

                "message":
                    "The diagnostic image is empty.",
            },
        )

    # --------------------------------------------------------
    # Temporary local file.
    #
    # Model interfaces currently accept image paths.
    # The temporary file belongs only to this request
    # and is always deleted.
    # --------------------------------------------------------

    temp_path: Path | None = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as temp_file:

            temp_file.write(
                data
            )

            temp_path = Path(
                temp_file.name
            )

        processing = (
            radiology_processor.process(
                image_path=temp_path,
                modality=normalized_modality,
            )
        )

        assessment = (
            radiology_assessment_builder.build(
                processing
            )
        )

    except UnsupportedRadiologyModalityError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "UNSUPPORTED_RADIOLOGY_MODALITY",

                "message":
                    "Unsupported radiology modality.",
            },
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code":
                    "RADIOLOGY_ANALYSIS_FAILED",

                "message":
                    (
                        "Radiology analysis "
                        "could not be completed."
                    ),
            },
        ) from exc

    finally:

        if (
            temp_path is not None
            and temp_path.exists()
        ):

            temp_path.unlink(
                missing_ok=True
            )

    return RadiologyAnalyzeResponse(
        modality=(
            assessment.modality.value
        ),

        classification=(
            assessment.classification
        ),

        probabilities=(
            assessment.probabilities
        ),

        confidence=(
            assessment.confidence
        ),

        inference_latency_ms=(
            assessment.inference_latency_ms
        ),

        model_name=(
            assessment.model_name
        ),

        model_version=(
            assessment.model_version
        ),

        limitations=list(
            assessment.limitations
        ),
    )


# ============================================================
# PATHOLOGY
# ============================================================

@app.post(
    "/v1/pathology/analyze",
    response_model=PathologyAnalyzeResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_pathology(
    file: UploadFile = File(
        ...,
    ),
) -> PathologyAnalyzeResponse:

    content_type = (
        file.content_type
        or ""
    ).strip().lower()

    suffix = (
        SUPPORTED_CONTENT_TYPES.get(
            content_type
        )
    )

    if suffix is None:

        raise HTTPException(
            status_code=(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
            ),
            detail={
                "code":
                    "UNSUPPORTED_DIAGNOSTIC_FILE_TYPE",

                "message":
                    (
                        "Only JPEG and PNG images "
                        "are supported."
                    ),
            },
        )

    try:

        data = await file.read(
            MAX_IMAGE_BYTES + 1
        )

    finally:

        await file.close()

    if len(data) > MAX_IMAGE_BYTES:

        raise HTTPException(
            status_code=(
                status.HTTP_413_CONTENT_TOO_LARGE
            ),
            detail={
                "code":
                    "DIAGNOSTIC_FILE_TOO_LARGE",

                "message":
                    (
                        "The diagnostic image exceeds "
                        "the allowed upload size."
                    ),
            },
        )

    if not data:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "EMPTY_DIAGNOSTIC_FILE",

                "message":
                    (
                        "The uploaded diagnostic "
                        "image is empty."
                    ),
            },
        )

    temp_path: Path | None = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as temp_file:

            temp_file.write(
                data
            )

            temp_path = Path(
                temp_file.name
            )

        try:

            pipeline = (
                get_pathology_pipeline()
            )

        except RuntimeError as exc:

            raise HTTPException(
                status_code=(
                    status.HTTP_503_SERVICE_UNAVAILABLE
                ),
                detail={
                    "code":
                        "PATHOLOGY_SERVICE_NOT_CONFIGURED",

                    "message":
                        (
                            "The pathology analysis "
                            "service is not configured."
                        ),
                },
            ) from exc

        pipeline_result = await (
            asyncio.to_thread(
                pipeline.run,
                temp_path,
            )
        )

        persistence_result = (
            pathology_persistence_builder
            .build(
                report=(
                    pipeline_result
                    .extracted_report
                ),
                processing=(
                    pipeline_result
                    .processing
                ),
            )
        )

        return PathologyAnalyzeResponse(
            schema_version=(
                persistence_result
                .schema_version
            ),

            document_type=(
                persistence_result
                .document_type
            ),

            unreadable_fields=(
                persistence_result
                .unreadable_fields
            ),

            results=(
                persistence_result
                .results
            ),
        )

    except HTTPException:

        raise

    except PathologyPersistenceContractError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code":
                    "PATHOLOGY_CONTRACT_ERROR",

                "message":
                    (
                        "The pathology result could "
                        "not be prepared safely."
                    ),
            },
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "code":
                    "PATHOLOGY_ANALYSIS_FAILED",

                "message":
                    (
                        "The pathology image could "
                        "not be analyzed right now."
                    ),
            },
        ) from exc

    finally:

        if (
            temp_path is not None
            and temp_path.exists()
        ):

            temp_path.unlink(
                missing_ok=True
            )    
