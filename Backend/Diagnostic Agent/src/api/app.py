from __future__ import annotations

import os
import tempfile
import json
from pathlib import Path
import logging
from time import perf_counter
from typing import Literal
from dotenv import load_dotenv

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

# The backend and Diagnostic Agent are separate processes. Load the shared
# backend environment file explicitly so the pathology vision provider can
# read OPENAI_API_KEY without exposing it to the browser.
load_dotenv(
    Path(__file__).resolve().parents[3] / ".env",
    override=False,
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

def _build_radiology_processor() -> RadiologyProcessor:
    chest_model_name = os.getenv("DIAGNOSTIC_CHEST_XRAY_MODEL", "xraydar").strip().lower()
    if chest_model_name == "xraydar":
        try:
            from src.diagnostics.radiology.xraydar_model import XRaydarChestXrayModel
        except ImportError as exc:
            if exc.name == "torch":
                raise RuntimeError(
                    "X-Raydar is enabled but PyTorch is missing from this Python environment. "
                    "Install the Diagnostic Agent optional requirements or set "
                    "DIAGNOSTIC_CHEST_XRAY_MODEL=mediscan to use the existing model."
                ) from exc
            raise
        chest_model = XRaydarChestXrayModel(
            model_dir=os.getenv("DIAGNOSTIC_XRAYDAR_MODEL_DIR")
        )
    elif chest_model_name in {"mediscan", "legacy"}:
        from src.diagnostics.radiology.chest_xray_model import ChestXrayModel
        chest_model = ChestXrayModel()
    else:
        raise RuntimeError("DIAGNOSTIC_CHEST_XRAY_MODEL must be 'xraydar' or 'mediscan'.")
    return RadiologyProcessor(chest_xray_model=chest_model)


radiology_processor = _build_radiology_processor()

radiology_assessment_builder = (
    RadiologyAssessmentBuilder()
)

pathology_pipeline: PathologyPipeline | None = None
vision_provider: OpenAILabVisionProvider | None = None

pathology_persistence_builder = (
    PathologyPersistenceContractBuilder()
)


def get_pathology_pipeline() -> PathologyPipeline:

    global pathology_pipeline

    if pathology_pipeline is None:
        extractor = (
            LabImageExtractor(
                get_vision_provider()
            )
        )

        pathology_pipeline = (
            PathologyPipeline(
                extractor=extractor
            )
        )

    return pathology_pipeline


def get_vision_provider() -> OpenAILabVisionProvider:
    global vision_provider
    if vision_provider is None:
        vision_provider = OpenAILabVisionProvider()
    return vision_provider


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

    score_semantics: str = "class_probability"


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
    "/v1/classify-image",
    response_model=ImageTypeClassificationResponse,
    status_code=status.HTTP_200_OK,
)
async def classify_image(
    file: UploadFile = File(...),
) -> ImageTypeClassificationResponse:
    content_type = (file.content_type or "").strip().lower()
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "UNSUPPORTED_DIAGNOSTIC_FILE_TYPE",
                "message": "Only JPEG and PNG images are supported.",
            },
        )

    try:
        image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    finally:
        await file.close()

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "DIAGNOSTIC_FILE_TOO_LARGE",
                "message": "The diagnostic image exceeds the allowed upload size.",
            },
        )
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EMPTY_DIAGNOSTIC_FILE",
                "message": "The uploaded diagnostic image is empty.",
            },
        )

    try:
        raw = await asyncio.to_thread(
            get_vision_provider().classify_image,
            image_bytes,
            content_type,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        return ImageTypeClassificationResponse.model_validate(
            json.loads(cleaned)
        )
    except Exception as exc:
        logger.exception("diagnostic_image_classification_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "IMAGE_CLASSIFICATION_FAILED",
                "message": "The image type could not be identified right now.",
            },
        ) from exc

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
        score_semantics=(
            "independent_multilabel_scores_not_calibrated_probabilities"
            if assessment.model_name == "xraydar-multiscale"
            else "class_probability"
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
