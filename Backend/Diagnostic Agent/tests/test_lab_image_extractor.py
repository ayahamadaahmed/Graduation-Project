from pathlib import Path

from src.diagnostics.lab_image_extractor import (
    LabImageExtractor,
    parse_lab_extraction,
)


class FakeVisionProvider:
    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> str:

        return """
        {
          "document_type": "cbc",
          "results": [
            {
              "raw_name": "HGB",
              "value": 9.6,
              "unit": "g/dL",
              "reference_min": 12,
              "reference_max": 16,
              "reference_text": "12 - 16"
            },
            {
              "raw_name": "WBC",
              "value": 14.2,
              "unit": "10^3/uL",
              "reference_min": 4,
              "reference_max": 11,
              "reference_text": "4 - 11"
            }
          ],
          "unreadable_fields": []
        }
        """


def test_parse_structured_lab_json():
    raw = """
    {
      "document_type": "cbc",
      "results": [
        {
          "raw_name": "HGB",
          "value": 9.6,
          "unit": "g/dL",
          "reference_min": 12,
          "reference_max": 16
        }
      ],
      "unreadable_fields": []
    }
    """

    report = parse_lab_extraction(raw)

    assert report.document_type == "cbc"
    assert len(report.results) == 1

    result = report.results[0]

    assert result.raw_name == "HGB"
    assert result.value == 9.6
    assert result.unit == "g/dL"
    assert result.reference_min == 12
    assert result.reference_max == 16


def test_unclear_value_becomes_none():
    raw = """
    {
      "document_type": "cbc",
      "results": [
        {
          "raw_name": "HGB",
          "value": null,
          "unit": "g/dL",
          "reference_min": 12,
          "reference_max": 16
        }
      ],
      "unreadable_fields": [
        "HGB value unclear"
      ]
    }
    """

    report = parse_lab_extraction(raw)

    assert report.results[0].value is None

    assert (
        "HGB value unclear"
        in report.unreadable_fields
    )


def test_fake_image_extraction(
    tmp_path: Path,
):
    image_path = (
        tmp_path
        / "cbc_sample.png"
    )

    image_path.write_bytes(
        b"fake-image-data"
    )

    extractor = LabImageExtractor(
        provider=FakeVisionProvider()
    )

    report = extractor.extract(
        image_path
    )

    assert report.document_type == "cbc"

    assert len(report.results) == 2

    assert (
        report.results[0].raw_name
        == "HGB"
    )

    assert (
        report.results[1].raw_name
        == "WBC"
    )


def test_invalid_json_is_rejected():
    try:
        parse_lab_extraction(
            "this is not json"
        )

        assert False

    except ValueError:
        assert True