from pathlib import Path

from src.diagnostics.lab_extraction_cache import (
    CachedLabImageExtractor,
)

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    ExtractedLabValue,
)


class CountingFakeExtractor:
    def __init__(self):
        self.calls = 0

    def extract(
        self,
        image_path,
    ):
        self.calls += 1

        return ExtractedLabReport(
            document_type="lft",
            results=[
                ExtractedLabValue(
                    raw_name="SGPT (ALT)",
                    value=36,
                    unit="U/L",
                    reference_min=13,
                    reference_max=40,
                    reference_text="13 - 40",
                )
            ],
            unreadable_fields=[],
        )


def test_same_image_is_extracted_once(
    tmp_path: Path,
):
    image = (
        tmp_path
        / "liver.png"
    )

    image.write_bytes(
        b"same-image"
    )

    base_extractor = (
        CountingFakeExtractor()
    )

    cached = CachedLabImageExtractor(
        extractor=base_extractor,
        cache_dir=tmp_path / "cache",
    )

    first = cached.extract(
        image
    )

    second = cached.extract(
        image
    )

    assert base_extractor.calls == 1

    assert (
        first.results[0].value
        == second.results[0].value
        == 36
    )

    assert (
        second.results[0].reference_max
        == 40
    )


def test_changed_image_is_extracted_again(
    tmp_path: Path,
):
    image = (
        tmp_path
        / "liver.png"
    )

    base_extractor = (
        CountingFakeExtractor()
    )

    cached = CachedLabImageExtractor(
        extractor=base_extractor,
        cache_dir=tmp_path / "cache",
    )

    image.write_bytes(
        b"version-one"
    )

    cached.extract(
        image
    )

    image.write_bytes(
        b"version-two"
    )

    cached.extract(
        image
    )

    assert base_extractor.calls == 2