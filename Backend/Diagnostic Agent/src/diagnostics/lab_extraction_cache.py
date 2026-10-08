from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    ExtractedLabValue,
)


class CachedLabImageExtractor:
    """
    Wraps a lab image extractor and caches its structured output.

    The same image + cache namespace is extracted only once.

    This helps:
    - reduce Vision API cost
    - reduce latency
    - prevent repeated extraction differences
    """

    def __init__(
        self,
        extractor,
        cache_dir: str | Path,
        cache_namespace: str = "lab-extraction-v1",
    ):
        self.extractor = extractor

        self.cache_dir = Path(cache_dir)

        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.cache_namespace = (
            cache_namespace
        )

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

        cache_key = self._build_cache_key(
            image_bytes
        )

        cache_file = (
            self.cache_dir
            / f"{cache_key}.json"
        )

        if cache_file.exists():
            return self._load(
                cache_file
            )

        report = self.extractor.extract(
            path
        )

        self._save(
            cache_file,
            report,
        )

        return report

    def _build_cache_key(
        self,
        image_bytes: bytes,
    ) -> str:

        hasher = hashlib.sha256()

        hasher.update(
            self.cache_namespace.encode(
                "utf-8"
            )
        )

        hasher.update(
            image_bytes
        )

        return hasher.hexdigest()

    @staticmethod
    def _save(
        path: Path,
        report: ExtractedLabReport,
    ) -> None:

        payload = {
            "document_type": (
                report.document_type
            ),
            "results": [
                asdict(result)
                for result in report.results
            ],
            "unreadable_fields": (
                report.unreadable_fields
            ),
        }

        temp_path = path.with_suffix(
            ".tmp"
        )

        temp_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temp_path.replace(path)

    @staticmethod
    def _load(
        path: Path,
    ) -> ExtractedLabReport:

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return ExtractedLabReport(
            document_type=payload.get(
                "document_type"
            ),
            results=[
                ExtractedLabValue(
                    **item
                )
                for item in payload.get(
                    "results",
                    [],
                )
            ],
            unreadable_fields=payload.get(
                "unreadable_fields",
                [],
            ),
        )