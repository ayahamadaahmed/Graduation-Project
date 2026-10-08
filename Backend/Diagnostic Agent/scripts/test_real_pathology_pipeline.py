from pathlib import Path

from dotenv import load_dotenv

from src.diagnostics.lab_extraction_cache import (
    CachedLabImageExtractor,
)

from src.diagnostics.lab_image_extractor import (
    LabImageExtractor,
    OpenAILabVisionProvider,
)

from src.diagnostics.pathology_pipeline import (
    PathologyPipeline,
)


load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

IMAGE_PATH = (
    ROOT
    / "samples"
    / "liver_sample.png"
)


def print_analysis(
    panel_name,
    analysis,
):
    if analysis is None:
        return

    print(f"\n[{panel_name.upper()}]")

    print("Findings:")

    for finding in analysis.findings:
        print(
            f"- {finding.name}: "
            f"{finding.value} "
            f"{finding.unit} "
            f"[{finding.flag.value}]"
        )

    print("Patterns:")

    for pattern in analysis.patterns:
        print(
            f"- {pattern.value}"
        )


def main():
    provider = OpenAILabVisionProvider()

    base_extractor = LabImageExtractor(
        provider=provider
    )

    extractor = CachedLabImageExtractor(
        extractor=base_extractor,
        cache_dir=(
            ROOT
            / ".cache"
            / "lab_extraction"
        ),
        cache_namespace=(
            f"lab-extraction-v1:"
            f"{provider.model_name}"
        ),
    )

    pipeline = PathologyPipeline(
        extractor=extractor
    )

    result = pipeline.run(
        IMAGE_PATH
    )

    processing = result.processing
    assessment = result.assessment

    print("=" * 70)
    print("UNIFIED PATHOLOGY PIPELINE")
    print("=" * 70)

    print("\nDocument type:")
    print(
        result.extracted_report.document_type
    )

    print("\nDetected panels:")

    if processing.detected_panels:
        for panel in (
            processing.detected_panels
        ):
            print(f"- {panel}")
    else:
        print("- None")

    print_analysis(
        "cbc",
        processing.cbc,
    )

    print_analysis(
        "glycemic",
        processing.glycemic,
    )

    print_analysis(
        "renal",
        processing.renal,
    )

    print_analysis(
        "liver",
        processing.liver,
    )

    print_analysis(
        "lipid",
        processing.lipid,
    )

    print("\nSkipped unreadable:")

    if processing.skipped_unreadable:
        for item in (
            processing.skipped_unreadable
        ):
            print(f"- {item}")
    else:
        print("- None")

    print("\nUnmapped tests:")

    if processing.unmapped_tests:
        for item in processing.unmapped_tests:
            print(f"- {item}")
    else:
        print("- None")

    print("\n" + "=" * 70)
    print("UNIFIED PATHOLOGY ASSESSMENT")
    print("=" * 70)

    print("\nDetected panels:")

    if assessment.detected_panels:
        for panel in assessment.detected_panels:
            print(f"- {panel}")
    else:
        print("- None")


    print("\nAbnormal findings:")

    if assessment.abnormal_findings:
        for finding in assessment.abnormal_findings:
            print(
                f"- {finding.name}: "
                f"{finding.value} "
                f"{finding.unit} "
                f"[{finding.flag.value}]"
            )
    else:
        print("- None")


    print("\nNormal findings:")

    if assessment.normal_findings:
        for finding in assessment.normal_findings:
            print(
                f"- {finding.name}: "
                f"{finding.value} "
                f"{finding.unit}"
            )
    else:
        print("- None")


    print("\nUnknown findings:")

    if assessment.unknown_findings:
        for finding in assessment.unknown_findings:
            print(
                f"- {finding.name}: "
                f"{finding.value} "
                f"{finding.unit}"
            )
    else:
        print("- None")


    print("\nSkipped unreadable:")

    if assessment.skipped_unreadable:
        for item in assessment.skipped_unreadable:
            print(f"- {item}")
    else:
        print("- None")


    print("\nUnmapped tests:")

    if assessment.unmapped_tests:
        for item in assessment.unmapped_tests:
            print(f"- {item}")
    else:
        print("- None")

if __name__ == "__main__":
    main()