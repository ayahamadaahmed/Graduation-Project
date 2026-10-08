from pathlib import Path

from dotenv import load_dotenv

from src.diagnostics.cbc_engine import LabFlag
from src.diagnostics.cbc_pipeline import CBCPipeline
from src.diagnostics.lab_image_extractor import (
    LabImageExtractor,
    OpenAILabVisionProvider,
)


load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

IMAGE_PATH = (
    ROOT
    / "samples"
    / "cbc_sample.png"
)


def main():
    provider = OpenAILabVisionProvider()

    extractor = LabImageExtractor(
        provider=provider
    )

    pipeline = CBCPipeline(
        extractor=extractor
    )

    result = pipeline.run(
        IMAGE_PATH
    )

    print("=" * 70)
    print("CBC END-TO-END PIPELINE")
    print("=" * 70)

    print("\nDocument:")
    print(
        result.extracted_report.document_type
    )

    print("\nNormalized values:")

    for item in result.normalized_results:
        print(
            f"- {item.raw_name}"
            f" -> {item.name}"
            f" = {item.value}"
            f" {item.unit}"
        )

    print("\nFindings:")

    for finding in result.analysis.findings:
        print(
            f"- {finding.name}: "
            f"{finding.value} "
            f"{finding.unit} "
            f"[{finding.flag.value}]"
        )

    print("\nAbnormal findings:")

    if not result.analysis.abnormal_findings:
        print("- None")
    else:
        for finding in (
            result.analysis.abnormal_findings
        ):
            print(
                f"- {finding.name}: "
                f"{finding.flag.value}"
            )

    print("\nCBC patterns:")

    for pattern in result.analysis.patterns:
        print(
            f"- {pattern.value}"
        )

    print("\nMissing core fields:")

    if not result.analysis.missing_fields:
        print("- None")
    else:
        for field in result.analysis.missing_fields:
            print(f"- {field}")

    if result.skipped_unreadable:
        print("\nSkipped unreadable:")

        for field in result.skipped_unreadable:
            print(f"- {field}")

    print("\nUnmapped tests:")

    if not result.unmapped_tests:
        print("- None")
    else:
        for test_name in result.unmapped_tests:
            print(f"- {test_name}")        


if __name__ == "__main__":
    main()