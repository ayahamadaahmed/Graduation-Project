from pathlib import Path

from dotenv import load_dotenv

from src.diagnostics.lab_image_extractor import (
    LabImageExtractor,
    OpenAILabVisionProvider,
)

from src.diagnostics.liver_pipeline import (
    LiverPipeline,
)
from src.diagnostics.lab_extraction_cache import (
    CachedLabImageExtractor,
)

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

IMAGE_PATH = (
    ROOT
    / "samples"
    / "liver_sample.png"
)


def main():
    
    provider = OpenAILabVisionProvider()

    base_extractor = LabImageExtractor(
        provider=provider
    )

    extractor = CachedLabImageExtractor(
        extractor=base_extractor,
        cache_dir=ROOT / ".cache" / "lab_extraction",
        cache_namespace=(
            f"lab-extraction-v1:{provider.model_name}"
        ),
    )

    pipeline = LiverPipeline(
        extractor=extractor
    )
    result = pipeline.run(
        IMAGE_PATH
    )

    print("=" * 70)
    print("LIVER END-TO-END PIPELINE")
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

    print("\nPatterns:")

    for pattern in result.analysis.patterns:
        print(
            f"- {pattern.value}"
        )

    print("\nSkipped unreadable:")

    if not result.skipped_unreadable:
        print("- None")
    else:
        for item in result.skipped_unreadable:
            print(f"- {item}")

    print("\nOut-of-scope tests:")

    if not result.out_of_scope_tests:
        print("- None")
    else:
        for item in result.out_of_scope_tests:
            print(f"- {item}")


if __name__ == "__main__":
    main()