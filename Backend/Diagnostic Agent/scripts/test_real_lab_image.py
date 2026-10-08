from pathlib import Path

from dotenv import load_dotenv

from src.diagnostics.lab_image_extractor import (
    LabImageExtractor,
    OpenAILabVisionProvider,
)


load_dotenv()


ROOT = Path(__file__).resolve().parents[1]

IMAGE_PATH = ROOT / "samples" / "liver_sample.png"


def main():
    provider = OpenAILabVisionProvider()

    extractor = LabImageExtractor(
        provider=provider
    )

    report = extractor.extract(
        IMAGE_PATH
    )

    print("=" * 70)
    print("LAB IMAGE EXTRACTION RESULT")
    print("=" * 70)

    print(
        f"\nDocument type: "
        f"{report.document_type}"
    )

    print("\nResults:")

    for result in report.results:
        print(
            f"- {result.raw_name}: "
            f"value={result.value}, "
            f"unit={result.unit}, "
            f"reference_min={result.reference_min}, "
            f"reference_max={result.reference_max}, "
            f"reference_text={result.reference_text}"
        )

    if report.unreadable_fields:
        print("\nUnreadable fields:")

        for field in report.unreadable_fields:
            print(f"- {field}")


if __name__ == "__main__":
    main()