from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
import base64
import os

from openai import OpenAI



@dataclass(frozen=True)
class ExtractedLabValue:
    raw_name: str
    value: float | None
    unit: str | None

    reference_min: float | None = None
    reference_max: float | None = None
    reference_text: str | None = None


@dataclass
class ExtractedLabReport:
    document_type: str | None = None
    results: list[ExtractedLabValue] = field(default_factory=list)
    unreadable_fields: list[str] = field(default_factory=list)


class VisionProvider(Protocol):
    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> str:
        ...


LAB_EXTRACTION_PROMPT = """
You are a medical laboratory DOCUMENT EXTRACTION system.

Your task is extraction only.

Do NOT:
- diagnose diseases
- interpret whether a value is clinically dangerous
- invent missing values
- change the values shown on the report

Read the uploaded laboratory report and return JSON only.

Required JSON format:

{
  "document_type": "cbc, vitamin D, iron studies, or other laboratory report",
  "results": [
    {
      "raw_name": "HGB",
      "value": 9.6,
      "unit": "g/dL",
      "reference_min": 12.0,
      "reference_max": 16.0,
      "reference_text": "12 - 16"
    }
  ],
  "unreadable_fields": []
}

Rules:

1. Preserve the test name exactly as shown in raw_name.
2. value must be numeric when clearly readable.
3. If a value is unclear, use null.
4. Do not guess units.
5. If the reference range is shown, extract it.
6. If only textual reference information exists, preserve it in reference_text.
7. If something cannot be read, add a short description to unreadable_fields.
8. Return valid JSON only.
9. Extract all clearly readable tests on the report, not only CBC tests. This
   includes vitamin D (25-OH/25-hydroxy vitamin D), ferritin, iron studies
   (serum iron, TIBC, transferrin saturation), vitamin B12, and folate when
   present. Preserve each printed name, value, unit, and reference range.
10. Set document_type to a short description of the report or panel(s) visible;
    do not label every laboratory report as CBC.
"""

IMAGE_TYPE_CLASSIFICATION_PROMPT = """
Classify the visible medical image type only. Do not read lab values,
interpret findings, diagnose conditions, or recommend treatment.

Return JSON only with this exact shape:
{"category":"pathology|chest_xray|brain_mri|kidney_ct|other","confidence":0.0}

Categories:
- pathology: a photographed or scanned laboratory report with text or values
- chest_xray: a chest radiograph
- brain_mri: a brain MRI image or scan
- kidney_ct: a CT image or scan of the kidneys
- other: anything else, unreadable, or not safely identifiable

Use a confidence from 0 to 1. Be conservative: choose other when unsure.
Classify from the image itself, not its filename or the user's message.
""".strip()

class OpenAILabVisionProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
    ):
        self.api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
        )

        self.model_name = (
            model_name
            or os.getenv("OPENAI_VISION_MODEL")
            or os.getenv("OPENAI_MODEL")
        )

        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured."
            )

        if not self.model_name:
            raise RuntimeError(
                "OPENAI_VISION_MODEL or OPENAI_MODEL "
                "is not configured."
            )

        self.client = OpenAI(
            api_key=self.api_key
        )

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> str:

        encoded = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        data_url = (
            f"data:{mime_type};base64,{encoded}"
        )

        response = self.client.responses.create(
            model=self.model_name,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": LAB_EXTRACTION_PROMPT,
                        },
                        {
                            "type": "input_image",
                            "image_url": data_url,
                        },
                    ],
                }
            ],
        )

        text = response.output_text

        if not text:
            raise RuntimeError(
                "OpenAI vision returned "
                "an empty response."
            )

        return text.strip()

    def classify_image(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> str:
        if not image_bytes:
            raise ValueError("image_bytes cannot be empty.")

        encoded = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"
        response = self.client.responses.create(
            model=self.model_name,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": IMAGE_TYPE_CLASSIFICATION_PROMPT,
                        },
                        {
                            "type": "input_image",
                            "image_url": data_url,
                        },
                    ],
                }
            ],
        )
        text = response.output_text
        if not text:
            raise RuntimeError("Vision image classifier returned an empty response.")
        return text.strip()


def _to_float(
    value,
) -> float | None:

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    try:
        return float(
            str(value)
            .strip()
            .replace(",", ".")
        )
    except (TypeError, ValueError):
        return None


def parse_lab_extraction(
    raw_response: str,
) -> ExtractedLabReport:

    cleaned = raw_response.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")

        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        payload = json.loads(cleaned)

    except json.JSONDecodeError as exc:
        raise ValueError(
            "Vision response is not valid JSON."
        ) from exc

    raw_results = payload.get("results")

    if not isinstance(raw_results, list):
        raise ValueError(
            "'results' must be a list."
        )

    results: list[ExtractedLabValue] = []

    for item in raw_results:
        if not isinstance(item, dict):
            continue

        raw_name = str(
            item.get("raw_name") or ""
        ).strip()

        if not raw_name:
            continue

        results.append(
            ExtractedLabValue(
                raw_name=raw_name,
                value=_to_float(
                    item.get("value")
                ),
                unit=(
                    str(item["unit"]).strip()
                    if item.get("unit")
                    else None
                ),
                reference_min=_to_float(
                    item.get("reference_min")
                ),
                reference_max=_to_float(
                    item.get("reference_max")
                ),
                reference_text=(
                    str(
                        item["reference_text"]
                    ).strip()
                    if item.get("reference_text")
                    else None
                ),
            )
        )

    unreadable = payload.get(
        "unreadable_fields",
        [],
    )

    if not isinstance(unreadable, list):
        unreadable = []

    return ExtractedLabReport(
        document_type=payload.get(
            "document_type"
        ),
        results=results,
        unreadable_fields=[
            str(item)
            for item in unreadable
        ],
    )


class LabImageExtractor:
    def __init__(
        self,
        provider: VisionProvider,
    ):
        self.provider = provider

    def extract(
        self,
        image_path: str | Path,
    ) -> ExtractedLabReport:

        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Image not found: {path}"
            )

        image_bytes = path.read_bytes()

        if not image_bytes:
            raise ValueError(
                "Image file is empty."
            )

        mime_type, _ = mimetypes.guess_type(
            path.name
        )

        mime_type = (
            mime_type
            or "application/octet-stream"
        )

        if not mime_type.startswith(
            "image/"
        ):
            raise ValueError(
                "This extractor currently accepts images only."
            )

        raw_response = self.provider.extract(
            image_bytes=image_bytes,
            mime_type=mime_type,
        )

        return parse_lab_extraction(
            raw_response
        )
